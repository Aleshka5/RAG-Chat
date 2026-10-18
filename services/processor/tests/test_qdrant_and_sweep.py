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
        self.exists = exists
        self.size = size
        self.created = None
        self.indexes: list[dict] = []
        self.payload_schema: dict[str, object] = {}

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs) -> None:
        self.created = kwargs
        self.exists = True

    def get_collection(self, collection_name: str):
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self.size))),
            payload_schema=dict(self.payload_schema),
        )

    def create_payload_index(self, **kwargs) -> None:
        self.indexes.append(kwargs)
        self.payload_schema[kwargs["field_name"]] = True


def test_collection_is_created_with_tenant_index() -> None:
    raw = RawQdrant(exists=False, size=768)
    store = QdrantStore(make_settings(embedding_dim=768), client=raw, sleeper=lambda _s: None)
    store.ensure_collection()
    assert raw.created["collection_name"] == "documents"
    assert raw.created["vectors_config"].size == 768
    assert raw.created["vectors_config"].distance == models.Distance.COSINE
    assert raw.created["hnsw_config"].m == 0
    assert raw.created["hnsw_config"].payload_m == 16
    by_field = {item["field_name"]: item["field_schema"] for item in raw.indexes}
    assert by_field["user_id"].is_tenant is True
    assert by_field["user_id"].type == models.KeywordIndexType.KEYWORD
    assert by_field["document_id"].type == models.KeywordIndexType.KEYWORD
    raw.created = None
    raw.indexes.clear()
    store.ensure_collection()
    assert raw.created is None
    assert raw.indexes == []


def test_wrong_dimension_refuses_to_start() -> None:
    raw = RawQdrant(exists=True, size=16)
    store = QdrantStore(make_settings(embedding_dim=768), client=raw, sleeper=lambda _s: None)
    with pytest.raises(SystemExit):
        store.ensure_collection()
    assert raw.created is None


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
