from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    DuplicateKeyError,
    ExecutionTimeout,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)
from rag_common.mongo import FILE_PAGES_INDEXES, FILES_INDEXES

from processor.config import Settings
from processor.errors import TransientFailure
from processor.retry import retry_call

CLAIM_STATUSES = ("uploaded", "error", "processing")
SKIP_STATUSES = ("ready", "deleting", "deleted")
_MONGO_TRANSIENT = (
    AutoReconnect,
    ConnectionFailure,
    ExecutionTimeout,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

EMPTY_CHECKPOINT = {
    "pages_done": 0,
    "pages_total": None,
    "chunks_done": 0,
    "chunks_total": None,
    "process_attempts": 0,
    "embedding_model": None,
    "chunk_tokens": None,
    "chunk_overlap": None,
}


def claim_filter(file_id: str, user_id: str, s3_key: str) -> dict[str, Any]:
    return {
        "file_id": file_id,
        "user_id": user_id,
        "s3_key": s3_key,
        "status": {"$in": list(CLAIM_STATUSES)},
    }


def claim_update(now: datetime) -> dict[str, Any]:
    return {"$set": {"status": "processing", "error": None, "updated_at": now}}


def pages_done_update(page_number: int, now: datetime) -> dict[str, Any]:
    return {
        "$max": {"checkpoint.pages_done": page_number},
        "$set": {"updated_at": now},
    }


def chunks_done_update(chunks_done: int, now: datetime) -> dict[str, Any]:
    return {
        "$max": {"checkpoint.chunks_done": chunks_done},
        "$set": {"updated_at": now},
    }


def ready_update(page_count: int, now: datetime) -> dict[str, Any]:
    return {
        "$set": {
            "status": "ready",
            "error": None,
            "page_count": page_count,
            "updated_at": now,
        },
        "$unset": {"checkpoint.reindex": ""},
    }


def image_ready_update(now: datetime) -> dict[str, Any]:
    """Same finished-file write as ``ready_update`` without page progress."""
    return {
        "$set": {
            "status": "ready",
            "error": None,
            "updated_at": now,
        },
        "$unset": {"checkpoint.reindex": ""},
    }


def error_update(code: str, now: datetime) -> dict[str, Any]:
    return {"$set": {"status": "error", "error": code, "updated_at": now}}


def processing_filter(file_id: str) -> dict[str, Any]:
    return {"file_id": file_id, "status": "processing"}


class MongoFiles:
    def __init__(
        self,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 3,
        client: MongoClient | None = None,
    ) -> None:
        self._sleep = sleeper
        self._attempts = attempts
        self._client = client or MongoClient(
            settings.mongodb_uri,
            tz_aware=True,
            tzinfo=UTC,
        )
        self._db = self._client.get_default_database()
        self.files = self._db["files"]
        self.pages = self._db["file_pages"]

    def ensure_indexes(self) -> None:
        def once() -> None:
            for spec in FILES_INDEXES:
                spec.create(self.files)
            for spec in FILE_PAGES_INDEXES:
                spec.create(self.pages)

        self._run(once)

    def get_by_file_id(self, file_id: str) -> dict[str, Any] | None:
        return self._run(lambda: self.files.find_one({"file_id": file_id}))

    def claim(self, file_id: str, user_id: str, s3_key: str, now: datetime) -> bool:
        def once() -> bool:
            updated = self.files.find_one_and_update(
                claim_filter(file_id, user_id, s3_key),
                claim_update(now),
                return_document=ReturnDocument.AFTER,
            )
            if updated is None:
                return False
            if updated.get("checkpoint") is None:
                self.files.update_one(
                    {"file_id": file_id, "status": "processing", "checkpoint": None},
                    {"$set": {"checkpoint": dict(EMPTY_CHECKPOINT)}},
                )
            return True

        return self._run(once)

    def set_attempts(self, file_id: str, *, reset: bool, now: datetime) -> int | None:
        def once() -> int | None:
            if reset:
                result = self.files.update_one(
                    processing_filter(file_id),
                    {"$set": {"checkpoint.process_attempts": 1, "updated_at": now}},
                )
                if result.matched_count == 0:
                    return None
                return 1
            updated = self.files.find_one_and_update(
                processing_filter(file_id),
                {"$inc": {"checkpoint.process_attempts": 1}, "$set": {"updated_at": now}},
                return_document=ReturnDocument.AFTER,
            )
            if updated is None:
                return None
            return int(updated["checkpoint"]["process_attempts"])

        return self._run(once)

    def mark_error(self, file_id: str, code: str, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(processing_filter(file_id), error_update(code, now))
            return result.matched_count == 1

        return self._run(once)

    def touch(self, file_id: str, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                {"$set": {"updated_at": now}},
            )
            return result.matched_count == 1

        return self._run(once)

    def note_opened(self, file_id: str, page_count: int, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                {
                    "$set": {
                        "page_count": page_count,
                        "checkpoint.pages_total": page_count,
                        "updated_at": now,
                    }
                },
            )
            return result.matched_count == 1

        return self._run(once)

    def page_exists(self, file_id: str, page_number: int) -> bool:
        def once() -> bool:
            return self.pages.find_one({"file_id": file_id, "page_number": page_number}, {"_id": 1}) is not None

        return self._run(once)

    def insert_page(self, page: dict[str, Any]) -> None:
        def once() -> None:
            try:
                self.pages.insert_one(dict(page))
            except DuplicateKeyError:
                return

        self._run(once)

    def list_pages(self, file_id: str) -> list[dict[str, Any]]:
        def once() -> list[dict[str, Any]]:
            cursor = self.pages.find({"file_id": file_id}).sort("page_number", 1)
            return list(cursor)

        return self._run(once)

    def advance_page(self, file_id: str, page_number: int, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                pages_done_update(page_number, now),
            )
            return result.matched_count == 1

        return self._run(once)

    def save_chunk_plan(
        self,
        file_id: str,
        *,
        chunks_total: int,
        chunks_done: int,
        embedding_model: str,
        chunk_tokens: int,
        chunk_overlap: int,
        now: datetime,
    ) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                {
                    "$set": {
                        "checkpoint.chunks_total": chunks_total,
                        "checkpoint.chunks_done": chunks_done,
                        "checkpoint.embedding_model": embedding_model,
                        "checkpoint.chunk_tokens": chunk_tokens,
                        "checkpoint.chunk_overlap": chunk_overlap,
                        "updated_at": now,
                    }
                },
            )
            return result.matched_count == 1

        return self._run(once)

    def advance_chunks(self, file_id: str, chunks_done: int, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                chunks_done_update(chunks_done, now),
            )
            return result.matched_count == 1

        return self._run(once)

    def reset_chunks(self, file_id: str, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(
                processing_filter(file_id),
                {
                    "$set": {
                        "checkpoint.chunks_done": 0,
                        "checkpoint.chunks_total": None,
                        "checkpoint.embedding_model": None,
                        "checkpoint.chunk_tokens": None,
                        "checkpoint.chunk_overlap": None,
                        "updated_at": now,
                    }
                },
            )
            return result.matched_count == 1

        return self._run(once)

    def mark_ready(self, file_id: str, page_count: int, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(processing_filter(file_id), ready_update(page_count, now))
            return result.matched_count == 1

        return self._run(once)

    def mark_image_ready(self, file_id: str, now: datetime) -> bool:
        def once() -> bool:
            result = self.files.update_one(processing_filter(file_id), image_ready_update(now))
            return result.matched_count == 1

        return self._run(once)

    def find_enqueue_failed(self, older_than: datetime) -> list[dict[str, Any]]:
        def once() -> list[dict[str, Any]]:
            return list(
                self.files.find(
                    {
                        "status": "error",
                        "error": "enqueue_failed",
                        "updated_at": {"$lt": older_than},
                    }
                )
            )

        return self._run(once)

    def _run(self, operation: Callable[[], Any]) -> Any:
        try:
            return retry_call(
                operation,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: isinstance(exc, _MONGO_TRANSIENT),
            )
        except _MONGO_TRANSIENT as exc:
            raise TransientFailure(
                "mongodb",
                permanent_code="processing_attempts_exceeded",
            ) from exc
