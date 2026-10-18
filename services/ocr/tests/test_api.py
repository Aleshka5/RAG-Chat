"""Request validation and response schema. The engine is a fake, so no weights are fetched."""

from __future__ import annotations

import io
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ocr_service.app import create_app
from ocr_service.config import Settings


class FakeEngine:
    def __init__(
        self,
        text: str = "распознанный текст",
        confidence: float | None = 0.92,
        delay: float = 0,
        fail: bool = False,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.delay = delay
        self.fail = fail
        self.calls = 0

    def recognize(self, image: Image.Image) -> tuple[str, float | None]:
        self.calls += 1
        assert image.mode == "RGB"
        assert image.size[0] > 0 and image.size[1] > 0
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("engine broke")
        return self.text, self.confidence


def _png(**kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (8, 8), "white")
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (6, 4), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


def _client(engine: FakeEngine, timeout: float = 30) -> TestClient:
    app = create_app(engine, Settings(ocr_timeout=timeout))
    return TestClient(app)


def test_health_ok_and_request_id() -> None:
    engine = FakeEngine()
    with _client(engine) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    uuid.UUID(response.headers["X-Request-Id"])
    assert engine.calls == 0


def test_health_echoes_request_id() -> None:
    request_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    with _client(FakeEngine()) as client:
        response = client.get("/health", headers={"X-Request-Id": request_id})
    assert response.headers["X-Request-Id"] == request_id


def test_ocr_response_schema() -> None:
    engine = FakeEngine(text="распознанный текст", confidence=0.92)
    with _client(engine) as client:
        response = client.post(
            "/ocr",
            files={"image": ("page.png", _png(), "image/png")},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"text", "confidence", "processing_time_ms"}
    assert body["text"] == "распознанный текст"
    assert body["confidence"] == pytest.approx(0.92)
    assert type(body["processing_time_ms"]) is int
    assert body["processing_time_ms"] >= 0
    uuid.UUID(response.headers["X-Request-Id"])
    assert engine.calls == 1


def test_empty_text_is_success() -> None:
    with _client(FakeEngine(text="", confidence=None)) as client:
        response = client.post(
            "/ocr",
            files={"image": ("page.png", _png(), "image/png")},
            headers={"X-Request-Id": "11111111-1111-4111-8111-111111111111"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "text": "",
        "confidence": None,
        "processing_time_ms": response.json()["processing_time_ms"],
    }
    assert type(response.json()["processing_time_ms"]) is int
    assert response.headers["X-Request-Id"] == "11111111-1111-4111-8111-111111111111"


def test_jpeg_is_accepted() -> None:
    with _client(FakeEngine(text="scan", confidence=0.5)) as client:
        response = client.post(
            "/ocr",
            files={"image": ("page.jpg", _jpeg(), "image/jpeg")},
        )
    assert response.status_code == 200
    assert response.json()["text"] == "scan"
    assert response.json()["confidence"] == pytest.approx(0.5)


def test_confidence_null_when_engine_has_no_score() -> None:
    with _client(FakeEngine(text="x", confidence=None)) as client:
        response = client.post("/ocr", files={"image": ("page.png", _png(), "image/png")})
    assert response.status_code == 200
    assert response.json()["text"] == "x"
    assert response.json()["confidence"] is None


@pytest.mark.parametrize(
    ("kwargs", "message_part"),
    [
        ({"data": {"unused": "1"}}, "multipart"),
        ({"files": {"file": ("page.png", b"png", "image/png")}}, "required"),
        ({"files": {"image": ("page.png", b"", "image/png")}}, "empty"),
        (
            {"files": {"image": ("page.bin", b"not-an-image", "application/octet-stream")}},
            "decoded",
        ),
        ({"content": b"%PDF-1.7\n", "headers": {"content-type": "application/pdf"}}, "multipart"),
    ],
)
def test_validation_errors(kwargs: dict, message_part: str) -> None:
    with _client(FakeEngine()) as client:
        response = client.post("/ocr", **kwargs)
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]
    assert message_part in body["error"]["message"].lower() or message_part == "multipart"
    assert body["error"]["details"]["fields"] == ["image"]
    uuid.UUID(response.headers["X-Request-Id"])


def test_json_body_is_validation_error() -> None:
    with _client(FakeEngine()) as client:
        response = client.post("/ocr", json={"image": "abc"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_timeout_is_upstream_timeout() -> None:
    engine = FakeEngine(delay=1.0)
    with _client(engine, timeout=0.15) as client:
        response = client.post("/ocr", files={"image": ("page.png", _png(), "image/png")})
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "upstream_timeout"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]
    uuid.UUID(response.headers["X-Request-Id"])


def test_engine_failure_is_json_error() -> None:
    with _client(FakeEngine(fail=True)) as client:
        response = client.post("/ocr", files={"image": ("page.png", _png(), "image/png")})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "engine broke" not in response.text


def test_invalid_request_id_is_replaced_with_uuid() -> None:
    with _client(FakeEngine()) as client:
        response = client.get("/health", headers={"X-Request-Id": "not-a-uuid"})
    parsed = uuid.UUID(response.headers["X-Request-Id"])
    assert str(parsed) != "not-a-uuid"


def test_confidence_is_clamped_into_unit_interval() -> None:
    with _client(FakeEngine(text="a", confidence=1.4)) as client:
        high = client.post("/ocr", files={"image": ("page.png", _png(), "image/png")})
    with _client(FakeEngine(text="b", confidence=-0.2)) as client:
        low = client.post("/ocr", files={"image": ("page.png", _png(), "image/png")})
    assert high.json()["confidence"] == 1
    assert low.json()["confidence"] == 0
