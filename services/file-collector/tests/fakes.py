"""In-memory Mongo, MinIO, and RabbitMQ stand-ins."""

import copy
from datetime import timedelta

from file_collector.clock import utcnow
from file_collector.errors import DuplicateActiveFile, ObjectNotFound, PublishError, StorageError
from file_collector.schema import (
    ACTIVE_STATUSES,
    deletion_allowed,
    file_indexes,
    rekey_filter,
    rekey_update,
)


class FakeFiles:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.indexes = None
        self.connected = False
        self.closed = False
        self.reads = 0
        self.blind_lookups = 0
        self.fail_insert = False
        self.updates: list[dict] = []
        self.before_rekey = None

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def ensure_indexes(self) -> None:
        self.indexes = file_indexes()

    async def find_active_by_hash(self, user_id: str, content_sha256: str) -> dict | None:
        if self._skip_lookup():
            return None
        for document in self.docs.values():
            if (
                document["user_id"] == user_id
                and document["content_sha256"] == content_sha256
                and document["status"] in ACTIVE_STATUSES
            ):
                return copy.deepcopy(document)
        return None

    def _skip_lookup(self) -> bool:
        if self.blind_lookups:
            self.blind_lookups -= 1
            return True
        return False

    async def find_active_by_s3_key(self, user_id: str, s3_key: str) -> dict | None:
        if self._skip_lookup():
            return None
        for document in self.docs.values():
            if (
                document["user_id"] == user_id
                and document["s3_key"] == s3_key
                and document["status"] in ACTIVE_STATUSES
            ):
                return copy.deepcopy(document)
        return None

    async def insert(self, document: dict) -> None:
        if self.fail_insert:
            raise StorageError("mongodb")
        if document["file_id"] in self.docs:
            raise StorageError("mongodb")
        key_match = None
        hash_match = None
        for existing in self.docs.values():
            if (
                existing["user_id"] != document["user_id"]
                or existing["status"] not in ACTIVE_STATUSES
            ):
                continue
            if existing["s3_key"] == document["s3_key"]:
                key_match = existing
            if existing["content_sha256"] == document["content_sha256"]:
                hash_match = existing
        winner = key_match or hash_match
        if winner is not None:
            raise DuplicateActiveFile(winner["file_id"])
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

    async def rekey(
        self,
        file_id: str,
        user_id: str,
        *,
        observed_key: str,
        new_key: str,
        content_sha256: str,
        same_key: bool,
        now,
        stale_seconds: int,
    ) -> dict | None:
        if self.before_rekey is not None:
            self.before_rekey()
        stale_before = now - timedelta(seconds=stale_seconds)
        query = rekey_filter(
            file_id,
            user_id,
            observed_key,
            content_sha256,
            same_key=same_key,
            stale_before=stale_before,
        )
        update = rekey_update(new_key, now)
        document = self.docs.get(file_id)
        if (
            document is None
            or document["user_id"] != user_id
            or not _rekey_matches(document, query)
        ):
            return None
        for other in self.docs.values():
            if other["file_id"] == file_id:
                continue
            if (
                other["user_id"] == user_id
                and other["s3_key"] == new_key
                and other["status"] in ACTIVE_STATUSES
            ):
                raise DuplicateActiveFile(other["file_id"])
        self.updates.append({"filter": copy.deepcopy(query), "update": copy.deepcopy(update)})
        _apply_set(document, update["$set"])
        return copy.deepcopy(document)


def _rekey_matches(document: dict, query: dict) -> bool:
    if document.get("file_id") != query["file_id"]:
        return False
    if document.get("user_id") != query["user_id"]:
        return False
    if document.get("s3_key") != query["s3_key"]:
        return False
    if document.get("content_sha256") != query["content_sha256"]:
        return False
    alternatives = query.get("$or")
    if alternatives is not None:
        return any(_rekey_clause(document, clause) for clause in alternatives)
    return _rekey_clause(document, {"status": query["status"]})


def _rekey_clause(document: dict, clause: dict) -> bool:
    status = clause["status"]
    if isinstance(status, dict):
        if document.get("status") not in status["$in"]:
            return False
    elif document.get("status") != status:
        return False
    bound = clause.get("updated_at")
    if bound is None:
        return True
    moment = document["updated_at"]
    limit = bound["$lt"]
    if moment.tzinfo is None and getattr(limit, "tzinfo", None) is not None:
        moment = moment.replace(tzinfo=limit.tzinfo)
    return moment < limit


def _apply_set(document: dict, values: dict) -> None:
    for key, value in values.items():
        cursor = document
        parts = key.split(".")
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = value


class FakeObjects:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.content_types: dict[str, str] = {}
        self.deletes: list[str] = []
        self.gets = 0
        self.heads = 0
        self.head_sizes: dict[str, int | None] = {}
        self.bucket = False
        self.closed = False
        self.fail_put = False
        self.fail_delete = False
        self.fail_get = False
        self.fail_head = False

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def ensure_bucket(self) -> None:
        self.bucket = True

    async def head(self, key: str) -> int | None:
        self.heads += 1
        if self.fail_head:
            raise StorageError("s3")
        if key not in self.objects:
            raise ObjectNotFound(key)
        if key in self.head_sizes:
            return self.head_sizes[key]
        return len(self.objects[key])

    async def put(self, key: str, data, length: int, content_type: str) -> None:
        payload = data.read()
        self.puts.append(key)
        self.content_types[key] = content_type
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
