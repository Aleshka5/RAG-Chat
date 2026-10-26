import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from deletion_worker.errors import (
    PermanentMessageError,
    StorageOperationError,
    TransientStorageError,
)
from deletion_worker.log import log_fields
from deletion_worker.messages import parse_delete_message
from deletion_worker.model import DeleteMessage, FileRecord, Outcome
from deletion_worker.ports import FileStore, ObjectStore, VectorStore

logger = logging.getLogger("deletion_worker")

_BACKOFF_SECONDS = (0.5, 1.0, 2.0)
_STEP_ATTEMPTS = 3
_FINAL_STATUS_ATTEMPTS = 2
_REREAD_LIMIT = 8
_ENTER_DELETING = {"uploaded", "ready", "error"}


class DeletionHandler:
    """Apply one doc.delete delivery.

    Order is fixed: claim, MinIO object when RAG owns the key, Qdrant points
    for user_id and document_id in the document collection and then the image
    collection, file_pages, then status deleted. object_owner=storage and keys
    under users/, _meta/, or shared/ skip the MinIO delete. Each storage step
    is idempotent so a crash before ack is finished by the next delivery. A
    missing image collection deletes nothing and the delivery continues.
    """

    def __init__(
        self,
        files: FileStore,
        objects: ObjectStore,
        vectors: VectorStore,
        *,
        stale_processing_seconds: int,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._files = files
        self._objects = objects
        self._vectors = vectors
        self._stale_processing_seconds = stale_processing_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep or _default_sleep

    def handle(self, raw: bytes | str, request_id: str | None = None) -> Outcome:
        try:
            message = parse_delete_message(raw)
        except PermanentMessageError as exc:
            logger.warning(
                "reject delete message",
                extra=log_fields(request_id=request_id, reason=exc.reason),
            )
            return Outcome.NACK
        try:
            return self._handle_message(message, request_id)
        except PermanentMessageError as exc:
            logger.warning(
                "reject delete delivery",
                extra=log_fields(
                    request_id=request_id,
                    message_id=message.message_id,
                    file_id=message.file_id,
                    user_id=message.user_id,
                    reason=exc.reason,
                ),
            )
            return Outcome.NACK
        except StorageOperationError as exc:
            logger.error(
                "delete step failed",
                extra=log_fields(
                    request_id=request_id,
                    message_id=message.message_id,
                    file_id=message.file_id,
                    user_id=message.user_id,
                    reason=exc.step,
                ),
            )
            return Outcome.NACK

    def _handle_message(self, message: DeleteMessage, request_id: str | None) -> Outcome:
        for _ in range(_REREAD_LIMIT):
            document = self._read_file(message.file_id)
            if document is None:
                self._purge(message.user_id, message.file_id, message.s3_key, "rag")
                return Outcome.ACK
            if document.status == "deleted":
                logger.info(
                    "delete already applied",
                    extra=log_fields(
                        request_id=request_id,
                        message_id=message.message_id,
                        file_id=message.file_id,
                        user_id=message.user_id,
                    ),
                )
                return Outcome.ACK
            if document.user_id != message.user_id:
                raise PermanentMessageError("user_mismatch")
            if document.status == "processing" and self._heartbeat_fresh(document.updated_at):
                raise PermanentMessageError("processing_active")
            if document.s3_key != message.s3_key:
                raise PermanentMessageError("s3_key_mismatch")
            if document.status != "deleting":
                self._enter_deleting(document)
                continue
            claim = self._ensure_claimed(message)
            if claim == "ack":
                return Outcome.ACK
            if claim == "reread":
                continue
            self._purge(
                document.user_id,
                document.file_id,
                document.s3_key,
                document.object_owner,
            )
            if not self._mark_deleted(message.file_id):
                raise PermanentMessageError("metadata_update_failed")
            logger.info(
                "file deleted",
                extra=log_fields(
                    request_id=request_id,
                    message_id=message.message_id,
                    file_id=message.file_id,
                    user_id=message.user_id,
                ),
            )
            return Outcome.ACK
        raise PermanentMessageError("concurrent_status")

    def _enter_deleting(self, document: FileRecord) -> bool:
        if not self._can_enter_deleting(document):
            raise PermanentMessageError("unexpected_status")
        now = self._clock()
        stale_before = now - timedelta(seconds=self._stale_processing_seconds)
        for attempt in range(_STEP_ATTEMPTS):
            try:
                return self._files.mark_deleting(document.file_id, now, stale_before)
            except TransientStorageError:
                if attempt == _STEP_ATTEMPTS - 1:
                    raise StorageOperationError("mark_deleting") from None
                self._sleep(_BACKOFF_SECONDS[attempt])
        raise StorageOperationError("mark_deleting")

    def _can_enter_deleting(self, document: FileRecord) -> bool:
        if document.status in _ENTER_DELETING:
            return True
        if document.status == "processing" and not self._heartbeat_fresh(document.updated_at):
            return True
        return False

    def _ensure_claimed(self, message: DeleteMessage) -> str:
        current = self._read_file(message.file_id)
        if current is None:
            return "reread"
        if current.status == "deleted":
            return "ack"
        if current.delete_claimed_at is not None and current.status == "deleting":
            return "go"
        if current.status != "deleting":
            return "reread"
        for attempt in range(_STEP_ATTEMPTS):
            now = self._clock()
            try:
                claimed = self._files.claim(message.file_id, now)
            except TransientStorageError:
                if attempt == _STEP_ATTEMPTS - 1:
                    self._bump_updated_at(message.file_id)
                    raise PermanentMessageError("claim_failed") from None
                self._sleep(_BACKOFF_SECONDS[attempt])
                continue
            if claimed:
                return "go"
            fresh = self._read_file(message.file_id)
            if fresh is None or fresh.status != "deleting":
                return "reread"
            if fresh.delete_claimed_at is not None:
                return "go"
            return "reread"
        self._bump_updated_at(message.file_id)
        raise PermanentMessageError("claim_failed")

    def _bump_updated_at(self, file_id: str) -> None:
        try:
            self._files.touch_updated_at(file_id, self._clock())
        except TransientStorageError:
            logger.warning(
                "failed to refresh updated_at after claim failure",
                extra=log_fields(file_id=file_id, reason="claim_failed"),
            )

    def _purge(self, user_id: str, file_id: str, s3_key: str, object_owner: str) -> None:
        if _deletes_object(s3_key, object_owner):
            self._retry("minio", lambda: self._objects.delete_object(s3_key))
        self._retry("qdrant", lambda: self._vectors.delete_points(user_id, file_id))
        self._retry("file_pages", lambda: self._files.delete_pages(file_id))

    def _mark_deleted(self, file_id: str) -> bool:
        for attempt in range(_FINAL_STATUS_ATTEMPTS):
            try:
                result = self._files.mark_deleted(file_id, self._clock())
            except TransientStorageError:
                if attempt == _FINAL_STATUS_ATTEMPTS - 1:
                    return False
                self._sleep(0.5)
                continue
            if result in {"updated", "already"}:
                return True
            if attempt == _FINAL_STATUS_ATTEMPTS - 1:
                return False
            self._sleep(0.5)
        return False

    def _retry(self, step: str, operation: Callable[[], None]) -> None:
        for attempt in range(_STEP_ATTEMPTS):
            try:
                operation()
                return
            except TransientStorageError:
                if attempt == _STEP_ATTEMPTS - 1:
                    raise StorageOperationError(step) from None
                self._sleep(_BACKOFF_SECONDS[attempt])

    def _read_file(self, file_id: str) -> FileRecord | None:
        for attempt in range(_STEP_ATTEMPTS):
            try:
                return self._files.get_file(file_id)
            except TransientStorageError:
                if attempt == _STEP_ATTEMPTS - 1:
                    raise StorageOperationError("mongo_read") from None
                self._sleep(_BACKOFF_SECONDS[attempt])
        raise StorageOperationError("mongo_read")

    def _heartbeat_fresh(self, updated_at: datetime | None) -> bool:
        if updated_at is None:
            return False
        age = (self._clock() - _as_utc(updated_at)).total_seconds()
        return age <= self._stale_processing_seconds


_FOREIGN_PREFIXES = ("users/", "_meta/", "shared/")


def _deletes_object(s3_key: str, object_owner: str) -> bool:
    if s3_key.startswith(_FOREIGN_PREFIXES):
        return False
    return object_owner.strip() != "storage"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _default_sleep(seconds: float) -> None:
    time.sleep(seconds)
