from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError
from qdrant_client.http.exceptions import UnexpectedResponse

from deletion_worker.errors import TransientStorageError
from deletion_worker.mongo_store import MongoFileStore
from deletion_worker.object_store import S3ObjectStore
from deletion_worker.vector_store import QdrantVectorStore

FILE_ID = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
NOW = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
STALE_BEFORE = datetime(2026, 10, 18, 19, 45, tzinfo=UTC)


class _Result:
    def __init__(self, matched_count: int = 0) -> None:
        self.matched_count = matched_count


class _Collection:
    def __init__(self) -> None:
        self.updates: list[tuple[dict[str, object], dict[str, object]]] = []
        self.indexes: list[tuple[object, dict[str, object]]] = []
        self.deleted: list[dict[str, object]] = []
        self.found: dict[str, object] | None = {"status": "deleted"}
        self.matched_count = 1

    def update_one(self, filt: dict[str, object], update: dict[str, object]) -> _Result:
        self.updates.append((filt, update))
        return _Result(self.matched_count)

    def find_one(self, filt: dict[str, object], projection: dict[str, int] | None = None) -> object:
        return self.found

    def delete_many(self, filt: dict[str, object]) -> _Result:
        self.deleted.append(filt)
        return _Result()

    def create_index(self, keys: object, **kwargs: object) -> str:
        self.indexes.append((keys, kwargs))
        return str(kwargs.get("name"))

    def find(self, filt: dict[str, object]) -> list[object]:
        return []


class _Database:
    def __init__(self) -> None:
        self.files = _Collection()
        self.pages = _Collection()

    def __getitem__(self, name: str) -> _Collection:
        if name == "files":
            return self.files
        if name == "file_pages":
            return self.pages
        raise KeyError(name)


class _Client:
    def __init__(self, database: _Database) -> None:
        self._database = database

    def get_default_database(self) -> _Database:
        return self._database


def test_mongo_conditional_filters_and_indexes() -> None:
    database = _Database()
    store = MongoFileStore(_Client(database))  # type: ignore[arg-type]
    store.ensure_indexes()
    assert store.mark_deleting(FILE_ID, NOW, STALE_BEFORE) is True
    assert store.claim(FILE_ID, NOW) is True
    database.files.matched_count = 0
    assert store.mark_deleted(FILE_ID, NOW) == "already"
    store.delete_pages(FILE_ID)

    deleting_filter = database.files.updates[0][0]
    assert deleting_filter["file_id"] == FILE_ID
    status_clause, processing_clause = deleting_filter["$or"]
    assert status_clause == {"status": {"$in": ["uploaded", "ready", "error"]}}
    assert processing_clause == {"status": "processing", "updated_at": {"$lt": STALE_BEFORE}}
    assert database.files.updates[0][1] == {"$set": {"status": "deleting", "updated_at": NOW}}

    assert database.files.updates[1][0] == {
        "file_id": FILE_ID,
        "status": "deleting",
        "delete_claimed_at": None,
    }
    assert database.files.updates[2][0] == {"file_id": FILE_ID, "status": "deleting"}
    assert database.files.updates[2][1]["$set"]["status"] == "deleted"
    assert database.pages.deleted == [{"file_id": FILE_ID}]

    index_names = [kwargs["name"] for _keys, kwargs in database.files.indexes]
    assert index_names == [
        "file_id_unique",
        "user_id_status",
        "user_id_created_at",
        "user_id_content_sha256_active",
    ]
    partial = database.files.indexes[-1][1]["partialFilterExpression"]
    assert partial == {"status": {"$in": ["uploaded", "processing", "ready", "error", "deleting"]}}
    assert database.pages.indexes[0][1]["name"] == "file_id_page_number"
    assert database.pages.indexes[0][1]["unique"] is True


def test_s3_delete_uses_bucket_and_treats_missing_key_as_success() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def delete_object(self, Bucket: str, Key: str) -> None:
            self.calls.append((Bucket, Key))

    client = Client()
    store = S3ObjectStore(client, "documents")
    store.delete_object("files/a")
    assert client.calls == [("documents", "files/a")]

    class Missing:
        def delete_object(self, Bucket: str, Key: str) -> None:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "gone"}}, "DeleteObject")

    S3ObjectStore(Missing(), "documents").delete_object("files/missing")

    class Broken:
        def delete_object(self, Bucket: str, Key: str) -> None:
            raise ClientError({"Error": {"Code": "InternalError", "Message": "x"}}, "DeleteObject")

    with pytest.raises(TransientStorageError):
        S3ObjectStore(Broken(), "documents").delete_object("files/a")


def test_qdrant_delete_filters_user_and_document() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def delete(self, collection_name: str, points_selector: object, wait: bool) -> None:
            self.calls.append(
                {
                    "collection_name": collection_name,
                    "points_selector": points_selector,
                    "wait": wait,
                }
            )

    client = Client()
    QdrantVectorStore(client, "documents").delete_points("user-1", "file-1")
    call = client.calls[0]
    assert call["collection_name"] == "documents"
    assert call["wait"] is True
    selector = call["points_selector"]
    must = selector.filter.must  # type: ignore[attr-defined]
    assert [(item.key, item.match.value) for item in must] == [
        ("user_id", "user-1"),
        ("document_id", "file-1"),
    ]

    class MissingCollection:
        def delete(self, collection_name: str, points_selector: object, wait: bool) -> None:
            raise UnexpectedResponse(404, "not found", b"", {})

    QdrantVectorStore(MissingCollection(), "documents").delete_points("user-1", "file-1")

    class Down:
        def delete(self, collection_name: str, points_selector: object, wait: bool) -> None:
            raise UnexpectedResponse(503, "down", b"", {})

    with pytest.raises(TransientStorageError):
        QdrantVectorStore(Down(), "documents").delete_points("user-1", "file-1")
