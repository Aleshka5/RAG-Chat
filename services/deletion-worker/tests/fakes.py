from dataclasses import replace
from datetime import datetime

from deletion_worker.errors import TransientStorageError
from deletion_worker.model import FileRecord


class MemoryFiles:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events
        self.docs: dict[str, FileRecord] = {}
        self.pages: dict[str, list[dict[str, object]]] = {}
        self.claim_failures = 0
        self.delete_failures = 0
        self.page_failures = 0

    def get_file(self, file_id: str) -> FileRecord | None:
        document = self.docs.get(file_id)
        if document is None:
            return None
        return replace(document)

    def mark_deleting(self, file_id: str, now: datetime, stale_before: datetime) -> bool:
        self.events.append(("mark_deleting", file_id))
        document = self.docs.get(file_id)
        if document is None:
            return False
        allowed = document.status in {"uploaded", "ready", "error"} or (
            document.status == "processing"
            and document.updated_at is not None
            and document.updated_at < stale_before
        )
        if not allowed:
            return False
        document.status = "deleting"
        document.updated_at = now
        return True

    def claim(self, file_id: str, now: datetime) -> bool:
        if self.claim_failures:
            self.claim_failures -= 1
            raise TransientStorageError("claim")
        self.events.append(("claim", file_id))
        document = self.docs.get(file_id)
        if document is None or document.status != "deleting":
            return False
        if document.delete_claimed_at is not None:
            return False
        document.delete_claimed_at = now
        document.updated_at = now
        return True

    def touch_updated_at(self, file_id: str, now: datetime) -> None:
        self.events.append(("touch_updated_at", file_id))
        document = self.docs.get(file_id)
        if document is not None:
            document.updated_at = now

    def mark_deleted(self, file_id: str, now: datetime) -> str:
        if self.delete_failures:
            self.delete_failures -= 1
            raise TransientStorageError("mark_deleted")
        self.events.append(("mark_deleted", file_id))
        document = self.docs.get(file_id)
        if document is None:
            return "already"
        if document.status == "deleted":
            return "already"
        if document.status != "deleting":
            return "conflict"
        document.status = "deleted"
        document.updated_at = now
        return "updated"

    def delete_pages(self, file_id: str) -> None:
        if self.page_failures:
            self.page_failures -= 1
            raise TransientStorageError("file_pages")
        self.events.append(("delete_pages", file_id))
        self.pages.pop(file_id, None)

    def find_unclaimed_deleting(self, older_than: datetime) -> list[FileRecord]:
        found: list[FileRecord] = []
        for document in self.docs.values():
            if document.status != "deleting" or document.delete_claimed_at is not None:
                continue
            if document.updated_at is None or document.updated_at < older_than:
                found.append(replace(document))
        return found


class MemoryObjects:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events
        self.objects: dict[str, bytes] = {}
        self.failures = 0
        self.crash_after_delete = False

    def delete_object(self, key: str) -> None:
        self.events.append(("delete_object", key))
        if self.failures:
            self.failures -= 1
            raise TransientStorageError("minio")
        self.objects.pop(key, None)
        if self.crash_after_delete:
            self.crash_after_delete = False
            raise RuntimeError("crash after object delete")


class MemoryVectors:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events
        self.points: dict[tuple[str, str], list[str]] = {}
        self.failures = 0

    def delete_points(self, user_id: str, document_id: str) -> None:
        self.events.append(("delete_points", user_id, document_id))
        if self.failures:
            self.failures -= 1
            raise TransientStorageError("qdrant")
        self.points.pop((user_id, document_id), None)


class MemoryPublisher:
    def __init__(self) -> None:
        self.published: list[FileRecord] = []
        self.fail_ids: set[str] = set()

    def publish_delete(self, file: FileRecord) -> None:
        if file.file_id in self.fail_ids:
            from deletion_worker.errors import PublishError

            raise PublishError("publish_not_confirmed")
        self.published.append(replace(file))


class RecordingChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.published: list[dict[str, object]] = []
        self.acks: list[int] = []
        self.nacks: list[tuple[int, bool]] = []

    def exchange_declare(self, **kwargs: object) -> None:
        self.calls.append(("exchange_declare", kwargs))

    def queue_declare(self, **kwargs: object) -> None:
        self.calls.append(("queue_declare", kwargs))

    def queue_bind(self, **kwargs: object) -> None:
        self.calls.append(("queue_bind", kwargs))

    def basic_qos(self, prefetch_count: int) -> None:
        self.calls.append(("basic_qos", prefetch_count))

    def basic_consume(self, queue: str, on_message_callback: object, auto_ack: bool) -> None:
        self.calls.append(("basic_consume", queue, auto_ack))

    def confirm_delivery(self) -> None:
        self.calls.append(("confirm_delivery",))

    def basic_publish(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        properties: object,
        mandatory: bool,
    ) -> bool:
        self.published.append(
            {
                "exchange": exchange,
                "routing_key": routing_key,
                "body": body,
                "properties": properties,
                "mandatory": mandatory,
            }
        )
        return True

    def basic_ack(self, delivery_tag: int) -> None:
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag: int, requeue: bool = True, multiple: bool = False) -> None:
        self.nacks.append((delivery_tag, requeue))
        self.calls.append(("basic_nack", delivery_tag, requeue, multiple))
