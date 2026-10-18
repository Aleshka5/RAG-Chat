import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from deletion_worker.errors import TransientStorageError
from deletion_worker.model import FileRecord

logger = logging.getLogger("deletion_worker")

_ACTIVE_STATUSES = ["uploaded", "processing", "ready", "error", "deleting"]


class MongoFileStore:
    def __init__(self, client: MongoClient[dict[str, Any]]) -> None:
        database = client.get_default_database()
        if database is None:
            logger.error("MONGODB_URI must include a database name")
            raise SystemExit(1)
        self._files = database["files"]
        self._pages = database["file_pages"]

    def ensure_indexes(self) -> None:
        self._files.create_index([("file_id", ASCENDING)], unique=True, name="file_id_unique")
        self._files.create_index(
            [("user_id", ASCENDING), ("status", ASCENDING)],
            name="user_id_status",
        )
        self._files.create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="user_id_created_at",
        )
        self._files.create_index(
            [("user_id", ASCENDING), ("content_sha256", ASCENDING)],
            unique=True,
            name="user_id_content_sha256_active",
            partialFilterExpression={"status": {"$in": _ACTIVE_STATUSES}},
        )
        self._pages.create_index(
            [("file_id", ASCENDING), ("page_number", ASCENDING)],
            unique=True,
            name="file_id_page_number_unique",
        )

    def get_file(self, file_id: str) -> FileRecord | None:
        try:
            document = self._files.find_one({"file_id": file_id})
        except PyMongoError as exc:
            raise TransientStorageError("mongo_read") from exc
        if document is None:
            return None
        return _record(document)

    def mark_deleting(self, file_id: str, now: datetime, stale_before: datetime) -> bool:
        try:
            result = self._files.update_one(
                {
                    "file_id": file_id,
                    "$or": [
                        {"status": {"$in": ["uploaded", "ready", "error"]}},
                        {"status": "processing", "updated_at": {"$lt": stale_before}},
                    ],
                },
                {"$set": {"status": "deleting", "updated_at": now}},
            )
        except PyMongoError as exc:
            raise TransientStorageError("mark_deleting") from exc
        return result.matched_count == 1

    def claim(self, file_id: str, now: datetime) -> bool:
        try:
            result = self._files.update_one(
                {"file_id": file_id, "status": "deleting", "delete_claimed_at": None},
                {"$set": {"delete_claimed_at": now, "updated_at": now}},
            )
        except PyMongoError as exc:
            raise TransientStorageError("claim") from exc
        return result.matched_count == 1

    def touch_updated_at(self, file_id: str, now: datetime) -> None:
        try:
            self._files.update_one({"file_id": file_id}, {"$set": {"updated_at": now}})
        except PyMongoError as exc:
            raise TransientStorageError("touch_updated_at") from exc

    def mark_deleted(self, file_id: str, now: datetime) -> str:
        try:
            result = self._files.update_one(
                {"file_id": file_id, "status": "deleting"},
                {"$set": {"status": "deleted", "updated_at": now}},
            )
            if result.matched_count == 1:
                return "updated"
            document = self._files.find_one({"file_id": file_id}, {"status": 1})
        except PyMongoError as exc:
            raise TransientStorageError("mark_deleted") from exc
        if document is None or document.get("status") == "deleted":
            return "already"
        return "conflict"

    def delete_pages(self, file_id: str) -> None:
        try:
            self._pages.delete_many({"file_id": file_id})
        except PyMongoError as exc:
            raise TransientStorageError("file_pages") from exc

    def find_unclaimed_deleting(self, older_than: datetime) -> list[FileRecord]:
        try:
            cursor = self._files.find(
                {
                    "status": "deleting",
                    "delete_claimed_at": None,
                    "$or": [
                        {"updated_at": {"$lt": older_than}},
                        {"updated_at": None},
                    ],
                }
            )
            return [_record(document) for document in cursor]
        except PyMongoError as exc:
            raise TransientStorageError("sweep_read") from exc


def connect_mongo(uri: str) -> MongoClient[dict[str, Any]]:
    client: MongoClient[dict[str, Any]] = MongoClient(uri, tz_aware=True, tzinfo=UTC)
    return client


def _record(document: dict[str, Any]) -> FileRecord:
    return FileRecord(
        file_id=str(document["file_id"]),
        user_id=str(document["user_id"]),
        s3_key=str(document.get("s3_key") or ""),
        status=str(document.get("status") or ""),
        updated_at=document.get("updated_at"),
        delete_claimed_at=document.get("delete_claimed_at"),
        error=document.get("error"),
    )
