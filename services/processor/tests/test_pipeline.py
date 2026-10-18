from __future__ import annotations

import uuid
from types import SimpleNamespace

from tests.fakes import FakeEmbed, FakeOcr, FakeQdrant, MemoryBlobs, MemoryFiles
from tests.support import (
    USER_ID,
    build_pipeline,
    file_document,
    make_settings,
    message_for,
    pdf_bytes,
)

from processor.consumer import make_consumer
from processor.errors import TransientFailure
from processor.points import point_id

LONG = "Hello world " * 20


class Broker:
    def __init__(self, body: bytes) -> None:
        self.main: list[bytes] = []
        self.dead: list[bytes] = []
        self.current: bytes | None = body

    def basic_ack(self, delivery_tag: int) -> None:
        self.current = None

    def basic_nack(self, delivery_tag: int, multiple: bool = False, requeue: bool = True) -> None:
        body = self.current
        self.current = None
        assert body is not None
        if requeue:
            self.main.append(body)
        else:
            self.dead.append(body)


def test_text_layer_pdf_reaches_ready_with_page_count() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG, LONG]))
    pipeline, ocr, embedding, qdrant = build_pipeline(settings, store, blobs)
    result = pipeline.handle(message_for(document), redelivered=False, headers={"x-request-id": "req-text"})
    assert result.action == "ack"
    saved = store.get_by_file_id(document["file_id"])
    assert saved is not None
    assert saved["status"] == "ready"
    assert saved["error"] is None
    assert saved["page_count"] == 2
    assert saved["checkpoint"]["pages_total"] == 2
    assert saved["checkpoint"]["pages_done"] == 2
    assert ocr.calls == []
    assert embedding.calls
    assert all(call["input_type"] == "document" for call in embedding.calls)
    assert all(call["title"] == "Отчёт.pdf" for call in embedding.calls)
    assert all(len(call["texts"]) <= 16 for call in embedding.calls)
    assert qdrant.points
    for point in qdrant.points.values():
        payload = point["payload"]
        assert payload["user_id"] == USER_ID
        assert payload["document_id"] == document["file_id"]
        assert payload["file_name"] == "Отчёт.pdf"
        assert payload["source"] == "text"
        assert point["id"] == point_id(document["file_id"], payload["chunk_index"])
        assert len(point["vector"]) == settings.embedding_dim
    assert store.pages_done_history == sorted(store.pages_done_history)
    assert store.pages_done_history[0] <= store.pages_done_history[-1]


def test_corrupt_pdf_sets_error_and_stays_in_the_collection() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(b"this is not a pdf")
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs)
    result = pipeline.handle(message_for(document), redelivered=False)
    assert result.action == "nack"
    assert result.requeue is False
    saved = store.get_by_file_id(document["file_id"])
    assert saved is not None
    assert saved["status"] == "error"
    assert saved["error"] == "corrupt_pdf"
    assert saved["page_count"] is None
    assert qdrant.points == {}
    assert ("upsert",) not in [(op[0],) for op in qdrant.ops]


def test_checkpoint_resume_does_not_ocr_finished_pages() -> None:
    settings = make_settings()
    document = file_document(
        status="processing",
        checkpoint={"pages_done": 1, "pages_total": 2, "process_attempts": 1},
    )
    store = MemoryFiles()
    store.add(document)
    store.insert_page(
        {
            "file_id": document["file_id"],
            "user_id": document["user_id"],
            "page_number": 1,
            "text": "already extracted page that must not be sent to OCR again",
            "origin": "ocr",
            "updated_at": document["updated_at"],
        }
    )
    blobs = MemoryBlobs(pdf_bytes(["", ""]))
    ocr = FakeOcr(text="текст со скана")
    pipeline, ocr, embedding, qdrant = build_pipeline(settings, store, blobs, ocr=ocr)
    result = pipeline.handle(message_for(document), redelivered=True, headers={"x-request-id": "resume"})
    assert result.action == "ack"
    assert len(ocr.calls) == 1
    assert ocr.calls[0]["png"].startswith(b"\x89PNG")
    assert ocr.calls[0]["request_id"] == "resume"
    pages = store.list_pages(document["file_id"])
    assert pages[0]["text"].startswith("already extracted")
    assert pages[0]["origin"] == "ocr"
    assert pages[1]["origin"] == "ocr"
    assert pages[1]["text"] == "текст со скана"
    saved = store.get_by_file_id(document["file_id"])
    assert saved["status"] == "ready"
    assert saved["page_count"] == 2
    assert saved["checkpoint"]["pages_done"] >= 1
    assert qdrant.points
    assert any(point["payload"]["source"] == "ocr" for point in qdrant.points.values())
    assert embedding.calls


def test_ocr_failure_keeps_finished_pages_and_retries_only_the_rest() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG, ""]))

    class FlakyOcr(FakeOcr):
        def recognize(self, png: bytes, request_id: str) -> str:
            self.calls.append({"png": png, "request_id": request_id})
            if len(self.calls) == 1:
                raise TransientFailure("ocr down", permanent_code="processing_attempts_exceeded")
            return "вторая страница"

    ocr = FlakyOcr()
    pipeline, ocr, _embedding, _qdrant = build_pipeline(settings, store, blobs, ocr=ocr)
    first = pipeline.handle(message_for(document), redelivered=False)
    assert first.action == "nack" and first.requeue is True
    assert store.get_by_file_id(document["file_id"])["status"] == "processing"
    assert store.get_by_file_id(document["file_id"])["error"] is None
    assert [page["page_number"] for page in store.list_pages(document["file_id"])] == [1]
    second = pipeline.handle(message_for(document), redelivered=True)
    assert second.action == "ack"
    assert len(ocr.calls) == 2
    assert store.get_by_file_id(document["file_id"])["status"] == "ready"
    assert store.pages_done_history == sorted(store.pages_done_history)


def test_pages_done_is_monotonic_including_when_already_ahead() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG, LONG, LONG]))
    pipeline, _ocr, _embedding, _qdrant = build_pipeline(settings, store, blobs)
    assert pipeline.handle(message_for(document), redelivered=False).action == "ack"
    assert store.pages_done_history == [1, 2, 3]

    ahead = file_document(
        file_id=str(uuid.uuid4()),
        status="processing",
        checkpoint={"pages_done": 5},
    )
    store.add(ahead)
    for number in (1, 2):
        store.insert_page(
            {
                "file_id": ahead["file_id"],
                "user_id": ahead["user_id"],
                "page_number": number,
                "text": LONG,
                "origin": "text",
                "updated_at": ahead["updated_at"],
            }
        )
    before = len(store.pages_done_history)
    blobs.data = pdf_bytes([LONG, LONG])
    assert pipeline.handle(message_for(ahead), redelivered=False).action == "ack"
    observed = store.pages_done_history[before:]
    assert observed
    assert all(value >= 5 for value in observed)
    assert observed == sorted(observed)
    assert store.get_by_file_id(ahead["file_id"])["checkpoint"]["pages_done"] >= 5


def test_embedding_batches_are_at_most_16() -> None:
    settings = make_settings(chunk_tokens=8, chunk_overlap_tokens=0, embedding_batch_size=16)
    document = file_document(checkpoint={"pages_done": 1, "pages_total": 1})
    store = MemoryFiles()
    store.add(document)
    store.insert_page(
        {
            "file_id": document["file_id"],
            "user_id": document["user_id"],
            "page_number": 1,
            "text": "a" * 200,
            "origin": "text",
            "updated_at": document["updated_at"],
        }
    )
    blobs = MemoryBlobs(pdf_bytes(["ignored because the page is already stored"]))
    pipeline, ocr, embedding, _qdrant = build_pipeline(settings, store, blobs)
    assert pipeline.handle(message_for(document), redelivered=False).action == "ack"
    assert ocr.calls == []
    sizes = [len(call["texts"]) for call in embedding.calls]
    assert sizes[0] == 16
    assert all(size <= 16 for size in sizes)
    assert sum(sizes) == 25


def test_empty_ocr_text_is_valid_and_fully_empty_file_is_no_extractable_text() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG, ""]))
    pipeline, ocr, _embedding, qdrant = build_pipeline(settings, store, blobs, ocr=FakeOcr(text=""))
    assert pipeline.handle(message_for(document), redelivered=False).action == "ack"
    pages = store.list_pages(document["file_id"])
    assert pages[1]["origin"] == "empty"
    assert pages[1]["text"] == ""
    assert store.get_by_file_id(document["file_id"])["status"] == "ready"

    empty = file_document(file_id=str(uuid.uuid4()))
    store.add(empty)
    blobs.data = pdf_bytes(["", ""])
    result = pipeline.handle(message_for(empty), redelivered=False)
    assert result.action == "nack" and result.requeue is False
    saved = store.get_by_file_id(empty["file_id"])
    assert saved["status"] == "error"
    assert saved["error"] == "no_extractable_text"
    assert saved is not None
    assert ("delete_file", empty["user_id"], empty["file_id"]) in qdrant.ops
    assert ocr.calls


def test_ready_and_mismatch_skip_work_without_changing_status() -> None:
    settings = make_settings()
    document = file_document(status="ready", page_count=3)
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG]))
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs)
    result = pipeline.handle(message_for(document), redelivered=True)
    assert result.action == "ack"
    assert blobs.reads == []
    assert qdrant.ops == []
    assert store.get_by_file_id(document["file_id"])["status"] == "ready"

    document["status"] = "uploaded"
    store.add(document)
    foreign = message_for(document, s3_key="files/other/key.pdf")
    result = pipeline.handle(foreign, redelivered=False)
    assert result.action == "nack" and result.requeue is False
    assert store.get_by_file_id(document["file_id"])["status"] == "uploaded"
    assert blobs.reads == []


def test_deleting_race_does_not_mark_ready_and_drops_points() -> None:
    settings = make_settings(chunk_tokens=8, chunk_overlap_tokens=0)
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG]))
    qdrant = FakeQdrant()
    qdrant.points["stale"] = {
        "id": "stale",
        "vector": [0.0] * settings.embedding_dim,
        "payload": {
            "user_id": document["user_id"],
            "document_id": document["file_id"],
            "chunk_index": 99,
            "text": "old",
        },
    }

    def flip_to_deleting(_texts, _title, _request_id) -> None:
        store.files[document["file_id"]]["status"] = "deleting"

    embedding = FakeEmbed(settings.embedding_dim, on_call=flip_to_deleting)
    pipeline, _ocr, embedding, qdrant = build_pipeline(settings, store, blobs, embedding=embedding, qdrant=qdrant)
    result = pipeline.handle(message_for(document), redelivered=False)
    assert result.action == "ack"
    assert store.get_by_file_id(document["file_id"])["status"] == "deleting"
    assert ("upsert",) not in [(op[0],) for op in qdrant.ops]
    assert qdrant.points == {}


def test_qdrant_failure_requeues_then_dead_letters_without_ack() -> None:
    settings = make_settings()
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG]))
    qdrant = FakeQdrant()
    qdrant.fail_upserts = 1
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs, qdrant=qdrant)
    body = message_for(document)
    delays: list[float] = []
    broker = Broker(body)
    callback = make_consumer(pipeline, sleeper=delays.append)
    callback(broker, SimpleNamespace(delivery_tag=1, redelivered=False), SimpleNamespace(headers=None), body)
    assert broker.dead == []
    assert broker.main == [body]
    assert broker.current is None
    saved = store.get_by_file_id(document["file_id"])
    assert saved["status"] == "processing"
    assert saved["error"] is None
    assert delays == [2.0]
    assert qdrant.points == {}

    settings_dead = make_settings(max_process_attempts=1)
    dead_store = MemoryFiles()
    dead_doc = file_document()
    dead_store.add(dead_doc)
    dead_qdrant = FakeQdrant()
    dead_qdrant.fail_upserts = 1
    dead_pipeline, _ocr, _embedding, dead_qdrant = build_pipeline(
        settings_dead,
        dead_store,
        MemoryBlobs(pdf_bytes([LONG])),
        qdrant=dead_qdrant,
    )
    dead_body = message_for(dead_doc)
    dead_broker = Broker(dead_body)
    make_consumer(dead_pipeline, sleeper=lambda _seconds: None)(
        dead_broker,
        SimpleNamespace(delivery_tag=2, redelivered=False),
        SimpleNamespace(headers=None),
        dead_body,
    )
    assert dead_broker.main == []
    assert dead_broker.dead == [dead_body]
    assert dead_broker.current is None
    failed = dead_store.get_by_file_id(dead_doc["file_id"])
    assert failed is not None
    assert failed["status"] == "error"
    assert failed["error"] == "index_write_failed"


def test_ninth_delivery_is_processing_attempts_exceeded_without_rereading_pdf() -> None:
    settings = make_settings()
    document = file_document(status="processing", checkpoint={"process_attempts": 8})
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG]))
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs)
    result = pipeline.handle(message_for(document), redelivered=True)
    assert result.action == "nack" and result.requeue is False
    assert blobs.reads == []
    assert qdrant.ops == []
    saved = store.get_by_file_id(document["file_id"])
    assert saved["status"] == "error"
    assert saved["error"] == "processing_attempts_exceeded"


def test_tail_delete_keeps_other_tenant_and_lower_chunks() -> None:
    settings = make_settings(chunk_tokens=8, chunk_overlap_tokens=0)
    document = file_document()
    store = MemoryFiles()
    store.add(document)
    store.insert_page(
        {
            "file_id": document["file_id"],
            "user_id": document["user_id"],
            "page_number": 1,
            "text": "abcdefgh",
            "origin": "text",
            "updated_at": document["updated_at"],
        }
    )
    blobs = MemoryBlobs(pdf_bytes(["x"]))
    qdrant = FakeQdrant()
    qdrant.points["tail"] = {
        "id": "tail",
        "vector": [1.0] * 4,
        "payload": {
            "user_id": document["user_id"],
            "document_id": document["file_id"],
            "chunk_index": 50,
        },
    }
    qdrant.points["other"] = {
        "id": "other",
        "vector": [1.0] * 4,
        "payload": {
            "user_id": str(uuid.uuid4()),
            "document_id": document["file_id"],
            "chunk_index": 50,
        },
    }
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs, qdrant=qdrant)
    assert pipeline.handle(message_for(document), redelivered=False).action == "ack"
    assert "tail" not in qdrant.points
    assert "other" in qdrant.points
    assert any(op[0] == "delete_tail" and op[3] == 1 for op in qdrant.ops)


def test_model_change_drops_points_and_resets_chunks_done() -> None:
    settings = make_settings(chunk_tokens=8, chunk_overlap_tokens=0)
    document = file_document(
        checkpoint={
            "embedding_model": "other/model",
            "chunk_tokens": 8,
            "chunk_overlap": 0,
            "chunks_done": 4,
        }
    )
    store = MemoryFiles()
    store.add(document)
    blobs = MemoryBlobs(pdf_bytes([LONG]))
    qdrant = FakeQdrant()
    qdrant.points["old"] = {
        "id": "old",
        "vector": [1.0] * 4,
        "payload": {
            "user_id": document["user_id"],
            "document_id": document["file_id"],
            "chunk_index": 0,
        },
    }
    pipeline, _ocr, _embedding, qdrant = build_pipeline(settings, store, blobs, qdrant=qdrant)
    assert pipeline.handle(message_for(document), redelivered=False).action == "ack"
    assert qdrant.ops[0][0] == "delete_file"
    saved = store.get_by_file_id(document["file_id"])
    assert saved["status"] == "ready"
    assert saved["checkpoint"]["embedding_model"] == settings.embedding_model
    assert saved["checkpoint"]["chunks_done"] == saved["checkpoint"]["chunks_total"]
    assert "old" not in qdrant.points
