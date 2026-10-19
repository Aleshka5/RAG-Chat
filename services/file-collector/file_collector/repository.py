"""MongoDB file metadata."""

import logging
from datetime import timedelta

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConfigurationError, DuplicateKeyError, PyMongoError

from file_collector.clock import utcnow
from file_collector.config import Settings
from file_collector.errors import DuplicateActiveFile, StorageError
from file_collector.schema import (
    ACTIVE_STATUSES,
    deletion_allowed,
    deletion_claim_filter,
    file_indexes,
)

logger = logging.getLogger("file_collector")


class MongoFiles:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None
        self._files = None

    async def connect(self) -> None:
        from motor.motor_asyncio import AsyncIOMotorClient

        self._client = AsyncIOMotorClient(
            self._settings.mongodb_uri,
            tz_aware=True,
            serverSelectionTimeoutMS=10000,
        )
        try:
            database = self._client.get_default_database()
        except ConfigurationError:
            database = self._client["rag"]
        self._files = database["files"]
        try:
            await database.command("ping")
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def ensure_indexes(self) -> None:
        collection = self._collection()
        for spec in file_indexes():
            kwargs: dict = {"unique": spec["unique"], "name": spec["name"]}
            if "partialFilterExpression" in spec:
                kwargs["partialFilterExpression"] = spec["partialFilterExpression"]
            keys = [
                (field, ASCENDING if direction == 1 else DESCENDING)
                for field, direction in spec["keys"]
            ]
            try:
                await collection.create_index(keys, **kwargs)
            except PyMongoError as exc:
                raise StorageError("mongodb") from exc

    async def find_active_by_hash(self, user_id: str, content_sha256: str) -> dict | None:
        try:
            return await self._collection().find_one(
                {
                    "user_id": user_id,
                    "content_sha256": content_sha256,
                    "status": {"$in": list(ACTIVE_STATUSES)},
                }
            )
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc

    async def insert(self, document: dict) -> None:
        try:
            await self._collection().insert_one(document)
        except DuplicateKeyError as exc:
            existing = await self.find_active_by_hash(
                document["user_id"],
                document["content_sha256"],
            )
            if existing is not None:
                raise DuplicateActiveFile(existing["file_id"]) from exc
            raise StorageError("mongodb") from exc
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc

    async def mark_enqueue_failed(self, file_id: str, user_id: str) -> None:
        try:
            result = await self._collection().update_one(
                {"file_id": file_id, "user_id": user_id},
                {
                    "$set": {
                        "status": "error",
                        "error": "enqueue_failed",
                        "updated_at": utcnow(),
                    }
                },
            )
        except PyMongoError as exc:
            logger.error(
                "failed to record enqueue_failed",
                extra={"file_id": file_id, "user_id": user_id},
            )
            raise StorageError("mongodb") from exc
        if result.matched_count != 1:
            logger.error(
                "failed to record enqueue_failed",
                extra={"file_id": file_id, "user_id": user_id},
            )

    async def get(self, file_id: str, user_id: str) -> dict | None:
        try:
            return await self._collection().find_one({"file_id": file_id, "user_id": user_id})
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc

    async def list_files(self, user_id: str, limit: int, offset: int) -> tuple[list[dict], int]:
        query = {"user_id": user_id, "status": {"$ne": "deleted"}}
        try:
            total = await self._collection().count_documents(query)
            cursor = (
                self._collection()
                .find(query)
                .sort("created_at", DESCENDING)
                .skip(offset)
                .limit(limit)
            )
            items = await cursor.to_list(length=limit)
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc
        return items, total

    async def claim_for_deletion(self, file_id: str, user_id: str, stale_seconds: int) -> str:
        collection = self._collection()
        try:
            for _ in range(3):
                now = utcnow()
                stale_before = now - timedelta(seconds=stale_seconds)
                result = await collection.update_one(
                    deletion_claim_filter(file_id, user_id, stale_before),
                    {"$set": {"status": "deleting", "updated_at": now}},
                )
                if result.matched_count:
                    return "ok"
                document = await collection.find_one({"file_id": file_id, "user_id": user_id})
                if document is None or document.get("status") == "deleted":
                    return "missing"
                if document.get("status") == "deleting":
                    return "busy"
                if deletion_allowed(document["status"], document["updated_at"], now, stale_seconds):
                    continue
                return "busy"
        except PyMongoError as exc:
            raise StorageError("mongodb") from exc
        return "busy"

    def _collection(self):
        if self._files is None:
            raise StorageError("mongodb")
        return self._files
