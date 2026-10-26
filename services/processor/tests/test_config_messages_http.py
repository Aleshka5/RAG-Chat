from __future__ import annotations

import base64
import json
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
from tests.support import clock_now, file_document, message_for

from processor.config import REQUIRED, load_settings
from processor.consumer import make_consumer
from processor.errors import InvalidMessage, PermanentFailure, TransientFailure
from processor.http_clients import EmbeddingClient, OcrClient
from processor.messages import build_process_message, parse_process_message
from processor.mongo_store import (
    claim_filter,
    claim_update,
    error_update,
    image_ready_update,
    pages_done_update,
    ready_update,
)
from processor.pipeline import DeliveryResult
from processor.sweeper import process_properties


def test_missing_secret_is_logged_by_name_only(caplog: pytest.LogCaptureFixture) -> None:
    env = {name: "configured" for name in REQUIRED}
    env["S3_SECRET_KEY"] = "super-secret-value"
    env["OCR_URL"] = ""
    with caplog.at_level(logging.ERROR, logger="processor"), pytest.raises(SystemExit):
        load_settings(env)
    assert "OCR_URL" in caplog.text
    assert "super-secret-value" not in caplog.text


def test_default_batch_size_attempts_and_overlap_guard() -> None:
    env = {name: "configured" for name in REQUIRED}
    env.update(
        {
            "MONGODB_URI": "mongodb://mongo:27017/rag",
            "S3_ENDPOINT": "http://minio:9000",
            "QDRANT_URL": "http://qdrant:6333",
            "RABBITMQ_URL": "amqp://rabbit:5672/",
            "EMBEDDING_URL": "http://embedding:8091",
            "OCR_URL": "http://ocr:8090",
        }
    )
    settings = load_settings(env)
    assert settings.embedding_batch_size == 16
    assert settings.max_process_attempts == 8
    assert settings.chunk_tokens == 512
    assert settings.chunk_overlap_tokens == 51
    assert settings.embedding_dim == 768
    assert settings.qdrant_collection == "documents"
    assert settings.qdrant_images_collection == "images"
    env["QDRANT_IMAGES_COLLECTION"] = "photos"
    assert load_settings(env).qdrant_images_collection == "photos"
    env["QDRANT_IMAGES_COLLECTION"] = ""
    assert load_settings(env).qdrant_images_collection == "images"
    env["CHUNK_OVERLAP_TOKENS"] = "512"
    with pytest.raises(SystemExit):
        load_settings(env)


def test_bad_message_and_schema_do_not_need_a_file() -> None:
    with pytest.raises(Exception):
        parse_process_message(b"{")
    body = json.loads(message_for(file_document()))
    body["schema_version"] = 2
    with pytest.raises(Exception):
        parse_process_message(json.dumps(body).encode())


def test_pages_done_update_uses_max() -> None:
    update = pages_done_update(4, clock_now())
    assert update["$max"]["checkpoint.pages_done"] == 4
    assert "checkpoint.pages_done" not in update["$set"]
    claim = claim_filter("file", "user", "files/user/file/a.pdf")
    assert claim["status"]["$in"] == ["uploaded", "error", "processing"]
    assert claim_update(clock_now())["$set"]["error"] is None
    assert ready_update(3, clock_now())["$set"]["status"] == "ready"
    assert error_update("corrupt_pdf", clock_now())["$set"]["error"] == "corrupt_pdf"
    finished = image_ready_update(clock_now())["$set"]
    assert finished["status"] == "ready"
    assert finished["error"] is None
    assert set(finished) == {"status", "error", "updated_at"}


def test_ocr_retries_5xx_not_4xx_and_embed_document_contract() -> None:
    delays: list[float] = []
    calls = {"ocr": 0}

    def ocr_handler(request: httpx.Request) -> httpx.Response:
        calls["ocr"] += 1
        assert request.url.path == "/ocr"
        assert request.headers["X-Request-Id"] == "req-1"
        assert b'name="image"' in request.content
        assert b"\x89PNG" in request.content
        if calls["ocr"] < 3:
            return httpx.Response(502, json={"error": {"code": "upstream", "message": "down"}})
        return httpx.Response(
            200,
            json={"text": "страница", "confidence": None, "processing_time_ms": 3},
        )

    ocr = OcrClient(
        "http://ocr:8090",
        timeout=5,
        max_attempts=3,
        sleeper=delays.append,
        transport=httpx.MockTransport(ocr_handler),
    )
    assert ocr.recognize(b"\x89PNG\r\n", "req-1") == "страница"
    assert delays == [0.5, 1.0]
    ocr.close()

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "validation_error", "message": "no"}})

    bad = OcrClient(
        "http://ocr:8090",
        timeout=5,
        max_attempts=3,
        sleeper=delays.append,
        transport=httpx.MockTransport(reject),
    )
    before = len(delays)
    with pytest.raises(Exception):
        bad.recognize(b"\x89PNG", "req-1")
    assert len(delays) == before
    bad.close()

    embed_delays: list[float] = []
    embed_calls = {"n": 0}

    def embed_handler(request: httpx.Request) -> httpx.Response:
        embed_calls["n"] += 1
        assert request.url.path == "/embed"
        body = json.loads(request.content)
        assert body["input_type"] == "document"
        assert body["title"] == "Отчёт.pdf"
        assert "model" not in body
        assert request.headers["X-Request-Id"] == "req-2"
        if embed_calls["n"] == 1:
            return httpx.Response(
                200,
                json={"embeddings": [[0.1]], "model": "google/embeddinggemma-2", "dimension": 1},
            )
        return httpx.Response(
            200,
            json={
                "embeddings": [[0.1, 0.2]],
                "model": "google/embeddinggemma-2",
                "dimension": 2,
            },
        )

    client = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=embed_delays.append,
        transport=httpx.MockTransport(embed_handler),
    )
    assert client.embed_documents(["чанк"], "Отчёт.pdf", "req-2") == [[0.1, 0.2]]
    assert embed_delays == [0.5]
    assert embed_calls["n"] == 2
    client.close()


def test_image_content_types_parse_and_other_types_are_rejected() -> None:
    document = file_document(content_type="image/png")
    message_id = str(uuid.uuid4())
    built = build_process_message(document, message_id, "2026-10-18T20:00:00Z")
    assert built["content_type"] == "image/png"
    parsed = parse_process_message(json.dumps(built).encode())
    assert parsed.content_type == "image/png"
    body = json.loads(message_for(file_document()))
    for content_type in (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        body["content_type"] = content_type
        assert parse_process_message(json.dumps(body).encode()).content_type == content_type
    body["content_type"] = "text/plain"
    with pytest.raises(InvalidMessage) as exc:
        parse_process_message(json.dumps(body).encode())
    assert exc.value.reason == "content_type"


def test_embed_image_posts_one_image_and_keeps_400_and_empty_permanent() -> None:
    raw = b"\x89PNG\r\n\x1a\nimage-bytes"
    encoded = base64.standard_b64encode(raw).decode("ascii")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embed/image"
        assert request.headers["X-Request-Id"] == "req-img"
        body = json.loads(request.content)
        seen.append(body)
        assert body == {"images": [encoded]}
        return httpx.Response(
            200,
            json={
                "embeddings": [[0.25, 0.5]],
                "model": "google/embeddinggemma-2",
                "dimension": 2,
            },
        )

    client = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=lambda _seconds: None,
        transport=httpx.MockTransport(handler),
    )
    assert client.embed_image(raw, "req-img") == [0.25, 0.5]
    assert seen == [{"images": [encoded]}]
    client.close()

    delays: list[float] = []
    calls = {"n": 0}

    def reject(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == "/embed/image"
        return httpx.Response(400, json={"error": {"code": "validation_error", "message": "bad image"}})

    bad = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=delays.append,
        transport=httpx.MockTransport(reject),
    )
    with pytest.raises(PermanentFailure) as exc:
        bad.embed_image(raw, "req-img")
    assert exc.value.code == "unsupported_image"
    assert calls["n"] == 1
    assert delays == []
    bad.close()

    def empty(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"embeddings": [], "model": "google/embeddinggemma-2", "dimension": 2},
        )

    blank = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=delays.append,
        transport=httpx.MockTransport(empty),
    )
    before = len(delays)
    with pytest.raises(PermanentFailure) as empty_exc:
        blank.embed_image(raw, "req-img")
    assert empty_exc.value.code == "unsupported_image"
    assert calls["n"] == 2
    assert len(delays) == before
    blank.close()

    def empty_vector(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"embeddings": [[]], "model": "google/embeddinggemma-2", "dimension": 2},
        )

    blank_vector = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=delays.append,
        transport=httpx.MockTransport(empty_vector),
    )
    with pytest.raises(PermanentFailure):
        blank_vector.embed_image(raw, "req-img")
    assert calls["n"] == 3
    assert delays == []
    blank_vector.close()


def test_embed_image_retries_502_and_504() -> None:
    delays: list[float] = []
    calls = {"n": 0}
    statuses = {1: 502, 2: 504}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.path == "/embed/image"
        status = statuses.get(calls["n"])
        if status is not None:
            return httpx.Response(status, json={"error": {"code": "upstream_failed", "message": "down"}})
        return httpx.Response(
            200,
            json={
                "embeddings": [[0.1, 0.2]],
                "model": "google/embeddinggemma-2",
                "dimension": 2,
            },
        )

    client = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=delays.append,
        transport=httpx.MockTransport(handler),
    )
    assert client.embed_image(b"\xff\xd8\xff", "req-img") == [0.1, 0.2]
    assert calls["n"] == 3
    assert delays == [0.5, 1.0]
    client.close()

    def always_down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, json={"error": {"code": "upstream_timeout", "message": "late"}})

    exhausted = EmbeddingClient(
        "http://embedding:8091",
        timeout=5,
        max_attempts=3,
        batch_size=16,
        dimension=2,
        model="google/embeddinggemma-2",
        sleeper=lambda _seconds: None,
        transport=httpx.MockTransport(always_down),
    )
    with pytest.raises(TransientFailure) as exc:
        exhausted.embed_image(b"\xff\xd8\xff", "req-img")
    assert exc.value.permanent_code == "embedding_failed"
    exhausted.close()


def test_publish_properties_and_consumer_settles_without_ack() -> None:
    props = process_properties("6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f", "req", timestamp=100)
    assert props.content_type == "application/json"
    assert props.content_encoding == "utf-8"
    assert props.delivery_mode == 2
    assert props.app_id == "processor"
    assert props.message_id == "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    assert props.headers["x-request-id"] == "req"
    assert props.timestamp == 100

    class Channel:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def basic_ack(self, delivery_tag: int) -> None:
            self.calls.append(("ack", delivery_tag))

        def basic_nack(self, delivery_tag: int, multiple: bool = False, requeue: bool = True) -> None:
            self.calls.append(("nack", delivery_tag, requeue))

    class Pipeline:
        def handle(self, body: bytes, *, redelivered: bool, headers: dict) -> DeliveryResult:
            assert redelivered is True
            assert headers["x-request-id"] == "req"
            return DeliveryResult.nack(requeue=False)

    channel = Channel()
    callback = make_consumer(Pipeline(), sleeper=lambda _seconds: None)
    callback(
        channel,
        SimpleNamespace(delivery_tag=9, redelivered=True),
        SimpleNamespace(headers={"x-request-id": "req"}),
        b"{}",
    )
    assert channel.calls == [("nack", 9, False)]
