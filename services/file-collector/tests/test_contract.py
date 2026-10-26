from datetime import UTC, datetime, timedelta

from file_collector.messages import (
    DELETE_ROUTING_KEY,
    DELETION_DEAD,
    DELETION_QUEUE,
    PROCESS_ROUTING_KEY,
    PROCESSING_DEAD,
    PROCESSING_QUEUE,
    delete_publication,
    process_publication,
    topology,
)
from file_collector.schema import (
    ACTIVE_STATUSES,
    deletion_allowed,
    deletion_claim_filter,
    file_indexes,
    rekey_filter,
    rekey_update,
)
from rag_common.mongo import FILES_INDEXES


def test_partial_unique_index_excludes_deleted() -> None:
    indexes = file_indexes()
    assert [tuple(spec["keys"]) for spec in indexes] == [spec.keys for spec in FILES_INDEXES]
    assert [spec["name"] for spec in indexes] == [spec.name for spec in FILES_INDEXES]
    assert [spec["unique"] for spec in indexes] == [spec.unique for spec in FILES_INDEXES]
    by_keys = {tuple(spec["keys"]): spec for spec in indexes}
    for keys in (
        (("user_id", 1), ("content_sha256", 1)),
        (("user_id", 1), ("s3_key", 1)),
    ):
        partial = by_keys[keys]
        assert partial["unique"] is True
        statuses = partial["partialFilterExpression"]["status"]["$in"]
        assert statuses == list(ACTIVE_STATUSES)
        assert "deleted" not in statuses
        shared = next(spec for spec in FILES_INDEXES if spec.keys == keys)
        assert partial["partialFilterExpression"] == shared.partial_filter_expression
    assert by_keys[(("user_id", 1), ("s3_key", 1))]["name"] == "user_id_s3_key_active"
    assert indexes[0]["unique"] is True


def test_topology_matches_messaging_spec() -> None:
    spec = topology("doc_events", "doc_events_dlq")
    assert spec["exchanges"] == [
        {"name": "doc_events", "type": "direct", "durable": True},
        {"name": "doc_events_dlq", "type": "direct", "durable": True},
    ]
    queues = {queue["name"]: queue for queue in spec["queues"]}
    assert queues[PROCESSING_QUEUE]["arguments"] == {
        "x-dead-letter-exchange": "doc_events_dlq",
        "x-dead-letter-routing-key": PROCESSING_DEAD,
    }
    assert queues[DELETION_QUEUE]["arguments"] == {
        "x-dead-letter-exchange": "doc_events_dlq",
        "x-dead-letter-routing-key": DELETION_DEAD,
    }
    assert queues[PROCESSING_DEAD]["arguments"] == {}
    assert queues[DELETION_DEAD]["arguments"] == {}
    assert all(queue["durable"] for queue in spec["queues"])
    assert spec["bindings"] == [
        {"queue": PROCESSING_QUEUE, "exchange": "doc_events", "routing_key": PROCESS_ROUTING_KEY},
        {"queue": DELETION_QUEUE, "exchange": "doc_events", "routing_key": DELETE_ROUTING_KEY},
        {"queue": PROCESSING_DEAD, "exchange": "doc_events_dlq", "routing_key": PROCESSING_DEAD},
        {"queue": DELETION_DEAD, "exchange": "doc_events_dlq", "routing_key": DELETION_DEAD},
    ]


def test_publications_use_persistent_json() -> None:
    moment = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
    routing, body, props = process_publication(
        message_id="f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5",
        file_id="6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
        user_id="91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
        s3_key="files/user/file/note.pdf",
        file_name="Отчёт.pdf",
        created_at=moment,
        request_id="11111111-1111-4111-8111-111111111111",
        timestamp=1_760_000_000,
    )
    assert routing == "doc.process"
    assert body["schema_version"] == 1
    assert body["message_type"] == "doc.process"
    assert body["content_type"] == "application/pdf"
    assert body["file_name"] == "Отчёт.pdf"
    assert body["created_at"] == "2026-10-18T20:00:00Z"
    assert body["message_id"] == props["message_id"]
    assert props["content_type"] == "application/json"
    assert props["content_encoding"] == "utf-8"
    assert props["delivery_mode"] == 2
    assert props["app_id"] == "file-collector"
    assert props["timestamp"] == 1_760_000_000
    assert props["headers"]["x-request-id"] == "11111111-1111-4111-8111-111111111111"

    delete_routing, delete_body, _delete_props = delete_publication(
        message_id="aabbccdd-1122-4333-8444-556677889900",
        file_id="6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
        user_id="91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
        s3_key="files/user/file/note.pdf",
        created_at=moment,
        request_id=None,
        timestamp=1_760_000_000,
    )
    assert delete_routing == "doc.delete"
    assert set(delete_body) == {
        "schema_version",
        "message_type",
        "message_id",
        "file_id",
        "user_id",
        "s3_key",
        "created_at",
    }
    assert delete_body["message_type"] == "doc.delete"


def test_fresh_processing_is_not_deletable_and_stale_processing_is() -> None:
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert deletion_allowed("uploaded", now, now, 900)
    assert deletion_allowed("ready", now, now, 900)
    assert deletion_allowed("error", now, now, 900)
    assert not deletion_allowed("processing", now, now, 900)
    assert not deletion_allowed("deleting", now, now, 900)
    assert not deletion_allowed("deleted", now, now, 900)
    fresh = now - timedelta(seconds=900)
    assert not deletion_allowed("processing", fresh, now, 900)
    stale = now - timedelta(seconds=900, microseconds=1)
    assert deletion_allowed("processing", stale, now, 900)
    claim = deletion_claim_filter("file", "user", fresh)
    assert claim["$or"][1] == {"status": "processing", "updated_at": {"$lt": fresh}}
    assert claim["$or"][0]["status"]["$in"] == ["uploaded", "ready", "error"]


def test_rekey_filter_excludes_deleting_and_resets_only_chunk_progress() -> None:
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    stale_before = now - timedelta(seconds=900)
    new_key = rekey_filter(
        "file",
        "user",
        "old/key",
        "ab" * 32,
        same_key=False,
        stale_before=stale_before,
    )
    assert new_key["s3_key"] == "old/key"
    assert new_key["content_sha256"] == "ab" * 32
    assert new_key["$or"][0]["status"]["$in"] == ["ready", "error"]
    assert new_key["$or"][1] == {"status": "processing", "updated_at": {"$lt": stale_before}}
    repeat = rekey_filter(
        "file",
        "user",
        "old/key",
        "ab" * 32,
        same_key=True,
        stale_before=stale_before,
    )
    assert repeat["status"]["$in"] == ["uploaded", "processing", "ready", "error"]
    assert "deleting" not in repeat["status"]["$in"]
    assert "deleted" not in repeat["status"]["$in"]
    update = rekey_update("users/new", now)
    assert set(update) == {"$set"}
    assert update["$set"]["s3_key"] == "users/new"
    assert update["$set"]["status"] == "processing"
    assert update["$set"]["page_count"] is None
    assert update["$set"]["checkpoint.chunks_done"] == 0
    assert update["$set"]["checkpoint.chunks_total"] is None
    assert "checkpoint.embedding_model" not in update["$set"]
    assert "checkpoint.chunk_tokens" not in update["$set"]
    assert "checkpoint.chunk_overlap" not in update["$set"]
    assert "file_pages" not in update["$set"]
