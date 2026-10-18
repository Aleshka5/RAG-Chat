import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from deletion_worker.errors import PublishError, TransientStorageError
from deletion_worker.log import log_fields
from deletion_worker.ports import DeletePublisher, FileStore

logger = logging.getLogger("deletion_worker")


class Sweeper:
    def __init__(
        self,
        files: FileStore,
        publisher: DeletePublisher,
        *,
        delete_requeue_after_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._files = files
        self._publisher = publisher
        self._delete_requeue_after_seconds = delete_requeue_after_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def run_once(self) -> int:
        older_than = self._clock() - timedelta(seconds=self._delete_requeue_after_seconds)
        try:
            pending = self._files.find_unclaimed_deleting(older_than)
        except TransientStorageError:
            logger.error("sweeper failed to read files", extra=log_fields(reason="sweep_read"))
            return 0
        published = 0
        for document in pending:
            try:
                self._publisher.publish_delete(document)
            except PublishError:
                logger.error(
                    "sweeper publish failed",
                    extra=log_fields(
                        file_id=document.file_id,
                        user_id=document.user_id,
                        reason="enqueue_failed",
                    ),
                )
                continue
            published += 1
            logger.info(
                "republished doc.delete",
                extra=log_fields(file_id=document.file_id, user_id=document.user_id),
            )
        return published
