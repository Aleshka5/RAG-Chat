from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from qdrant_client import models
from tests.fakes import MemoryFiles
from tests.support import clock_now, file_document, make_settings

from processor.qdrant_store import QdrantStore
from processor.sweeper import sweep_enqueue_failed
from processor.timeutil import format_z


class RawQdrant:
    def __init__(self, *, exists: bool, size: int) -> None:
        self.initial_exists = exists
        self.size = size
        self.created: list[dict] = []
        self.indexes: list[dict] = []
        self.payload_schema: dict[str, dict[str, object]] = {}
        self.known: set[str] = set()

    def collection_exists(self, collection_name: str) -> bool:
        if collection_name in self.known:
            return True
        return self.initial_exists

    def create_collection(self, **kwargs) -> None:
        self.created.append(kwargs)
        self.known.add(kwargs["collection_name"])

    def get_collection(self, collection_name: str):
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self.size))),
            payload_schema=dict(self.payload_schema.get(collection_name, {})),
        )

    def create_payload_index(self, **kwargs) -> None:
        self.indexes.append(kwargs)
        self.payload_schema.setdefault(kwargs["collection_name"], {})[kwargs["field_name"]] = True


def _index_by_collection(raw: RawQdrant) -> dict[str, dict]:
    by_collection: dict[str, dict] = {}
    for item in raw.indexes:
        by_collection.setdefault(item["collection_name"], {})[item["field_name"]] = item["field_schema"]
    return by_collection


def test_collection_is_created_with_tenant_index() -> None:
    raw = RawQdrant(exists=False, size=768)
    store = QdrantStore(make_settings(embedding_dim=768), client=raw, sleeper=lambda _s: None)
    store.ensure_collection()
    assert [item["collection_name"] for item in raw.created] == ["documents", "images"]
    for created in raw.created:
        assert created["vectors_config"].size == 768
        assert created["vectors_config"].distance == models.Distance.COSINE
        assert created["hnsw_config"].m == 0
        assert created["hnsw_config"].payload_m == 16
    by_collection = _index_by_collection(raw)
    assert set(by_collection) == {"documents", "images"}
    for schema in by_collection.values():
        assert schema["user_id"].is_tenant is True
        assert schema["user_id"].type == models.KeywordIndexType.KEYWORD
        assert schema["document_id"].type == models.KeywordIndexType.KEYWORD
    raw.created.clear()
    raw.indexes.clear()
    store.ensure_collection()
    assert raw.created == []
    assert raw.indexes == []


def test_wrong_dimension_refuses_to_start() -> None:
    raw = RawQdrant(exists=True, size=16)
    store = QdrantStore(make_settings(embedding_dim=768), client=raw, sleeper=lambda _s: None)
    with pytest.raises(SystemExit):
        store.ensure_collection()
    assert raw.created == []


class RecordingQdrant:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deletes: list[dict] = []

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def delete(self, **kwargs) -> None:
        self.deletes.append(kwargs)


def test_image_upsert_and_delete_use_the_images_collection() -> None:
    raw = RecordingQdrant()
    settings = make_settings(qdrant_images_collection="images")
    store = QdrantStore(settings, client=raw, sleeper=lambda _s: None)
    store.upsert_points([{"id": "doc", "vector": [0.1] * settings.embedding_dim, "payload": {"text": "a"}}])
    store.upsert_images([{"id": "img", "vector": [0.2] * settings.embedding_dim, "payload": {"file_id": "file-1"}}])
    store.delete_file("user-1", "file-1")
    store.delete_image("user-1", "file-1")
    assert [item["collection_name"] for item in raw.upserts] == ["documents", "images"]
    assert [item["collection_name"] for item in raw.deletes] == ["documents", "images"]
    image_filter = raw.deletes[1]["points_selector"].filter
    assert [item.key for item in image_filter.must] == ["user_id", "document_id"]
    assert image_filter.must[0].match.value == "user-1"
    assert image_filter.must[1].match.value == "file-1"
    assert raw.upserts[1]["points"][0].payload == {"file_id": "file-1"}


class Publisher:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.bodies: list[dict] = []

    def publish_doc_process(self, body: dict, message_id: str, request_id: str) -> None:
        if self.fail:
            raise RuntimeError("confirm nack")
        assert body["message_id"] == message_id
        assert request_id
        self.bodies.append(body)


def test_sweeper_republishes_only_stale_enqueue_failed() -> None:
    now = clock_now()
    store = MemoryFiles()
    stale = file_document(
        status="error",
        error="enqueue_failed",
        updated_at=now - timedelta(seconds=121),
    )
    fresh = file_document(
        file_id="11111111-1111-4111-8111-111111111111",
        status="error",
        error="enqueue_failed",
        updated_at=now - timedelta(seconds=10),
    )
    corrupt = file_document(
        file_id="22222222-2222-4222-8222-222222222222",
        status="error",
        error="corrupt_pdf",
        updated_at=now - timedelta(seconds=500),
    )
    store.add(stale)
    store.add(fresh)
    store.add(corrupt)
    publisher = Publisher()
    published = sweep_enqueue_failed(store, publisher, now=now, older_than_seconds=120)
    assert published == 1
    body = publisher.bodies[0]
    assert body["schema_version"] == 1
    assert body["message_type"] == "doc.process"
    assert body["file_id"] == stale["file_id"]
    assert body["s3_key"] == stale["s3_key"]
    assert body["file_name"] == "Отчёт.pdf"
    assert body["created_at"] == format_z(now)
    assert store.get_by_file_id(stale["file_id"])["status"] == "error"
    assert store.get_by_file_id(stale["file_id"])["error"] == "enqueue_failed"

    failing = Publisher(fail=True)
    assert sweep_enqueue_failed(store, failing, now=now, older_than_seconds=120) == 0
    assert store.get_by_file_id(stale["file_id"])["error"] == "enqueue_failed"
