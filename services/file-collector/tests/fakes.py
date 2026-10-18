"""In-memory Mongo, MinIO, and RabbitMQ stand-ins."""

import copy

from file_collector.clock import utcnow
from file_collector.errors import DuplicateActiveFile, PublishError, StorageError
from file_collector.schema import ACTIVE_STATUSES, deletion_allowed, file_indexes


class FakeFiles:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.indexes = None
        self.connected = False
        self.closed = False
        self.reads = 0
        self.blind_lookups = 0
        self.fail_insert = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def ensure_indexes(self) -> None:
        self.indexes = file_indexes()

    async def find_active_by_hash(self, user_id: str, content_sha256: str) -> dict | None:
        if self.blind_lookups:
            self.blind_lookups -= 1
            return None
        for document in self.docs.values():
            if (
                document["user_id"] == user_id
                and document["content_sha256"] == content_sha256
                and document["status"] in ACTIVE_STATUSES
            ):
                return copy.deepcopy(document)
        return None

    async def insert(self, document: dict) -> None:
        if self.fail_insert:
            raise StorageError("mongodb")
        if document["file_id"] in self.docs:
            raise StorageError("mongodb")
        for existing in self.docs.values():
            if (
                existing["user_id"] == document["user_id"]
                and existing["content_sha256"] == document["content_sha256"]
                and existing["status"] in ACTIVE_STATUSES
            ):
                raise DuplicateActiveFile(existing["file_id"])
        self.docs[document["file_id"]] = copy.deepcopy(document)

    async def mark_enqueue_failed(self, file_id: str, user_id: str) -> None:
        document = self.docs.get(file_id)
        if document is None or document["user_id"] != user_id:
            return
        document["status"] = "error"
        document["error"] = "enqueue_failed"
        document["updated_at"] = utcnow()

    async def get(self, file_id: str, user_id: str) -> dict | None:
        self.reads += 1
        document = self.docs.get(file_id)
        if document is None or document["user_id"] != user_id:
            return None
        return copy.deepcopy(document)

    async def list_files(self, user_id: str, limit: int, offset: int) -> tuple[list[dict], int]:
        self.reads += 1
        matched = [
            document
            for document in self.docs.values()
            if document["user_id"] == user_id and document["status"] != "deleted"
        ]
        matched.sort(key=lambda document: document["created_at"], reverse=True)
        page = matched[offset : offset + limit]
        return [copy.deepcopy(document) for document in page], len(matched)

    async def claim_for_deletion(self, file_id: str, user_id: str, stale_seconds: int) -> str:
        document = self.docs.get(file_id)
        if document is None or document["user_id"] != user_id or document["status"] == "deleted":
            return "missing"
        if document["status"] == "deleting":
            return "busy"
        now = utcnow()
        if not deletion_allowed(document["status"], document["updated_at"], now, stale_seconds):
            return "busy"
        document["status"] = "deleting"
        document["updated_at"] = now
        return "ok"


class FakeObjects:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []
        self.gets = 0
        self.bucket = False
        self.closed = False
        self.fail_put = False
        self.fail_delete = False
        self.fail_get = False

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def ensure_bucket(self) -> None:
        self.bucket = True

    async def put(self, key: str, data, length: int) -> None:
        payload = data.read()
        self.puts.append(key)
        if self.fail_put:
            raise StorageError("s3")
        if len(payload) != length:
            raise StorageError("s3")
        self.objects[key] = payload

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        if self.fail_delete:
            raise StorageError("s3")
        self.objects.pop(key, None)

    async def get(self, key: str) -> bytes:
        self.gets += 1
        if self.fail_get or key not in self.objects:
            raise StorageError("s3")
        return self.objects[key]


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict, dict]] = []
        self.fail = False
        self.remaining_failures = 0
        self.topology_ready = False
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def ensure_topology(self) -> None:
        self.topology_ready = True

    async def publish(self, routing_key: str, body: dict, properties: dict) -> None:
        if self.fail or self.remaining_failures > 0:
            if self.remaining_failures > 0:
                self.remaining_failures -= 1
            raise PublishError("nack")
        self.messages.append((routing_key, copy.deepcopy(body), copy.deepcopy(properties)))
