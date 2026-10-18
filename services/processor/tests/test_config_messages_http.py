from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from tests.support import clock_now, file_document, message_for

from processor.config import REQUIRED, load_settings
from processor.consumer import make_consumer
from processor.http_clients import EmbeddingClient, OcrClient
from processor.messages import parse_process_message
from processor.mongo_store import (
    claim_filter,
    claim_update,
    error_update,
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
