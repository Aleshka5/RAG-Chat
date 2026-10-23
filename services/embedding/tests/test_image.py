"""The image modality: one vector per image, in the same space as text."""

import base64
import json
import math
import struct
import zlib

import httpx
import pytest
from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from embedding.encoder import LlamaEncoder
from embedding.errors import UpstreamFailed, UpstreamTimeout
from tests.fakes import FakeCounter, FakeEncoder, unit_vector


def png_bytes() -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def test_one_vector_per_image_in_the_text_space(client: TestClient, encoder: FakeEncoder) -> None:
    first, second = png_bytes(), png_bytes() + b"\x00"
    response = client.post("/embed/image", json={"images": [b64(first), b64(second)]})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "google/embeddinggemma-2"
    assert body["dimension"] == 768
    assert len(body["embeddings"]) == 2
    assert all(len(vector) == 768 for vector in body["embeddings"])
    assert encoder.image_batches == [[first, second]]
    assert encoder.seen == []


def test_text_fields_are_refused_on_the_image_route(
    client: TestClient, encoder: FakeEncoder
) -> None:
    for field, value in (
        ("texts", ["chunk"]),
        ("input_type", "document"),
        ("title", "Отчёт.pdf"),
    ):
        payload = {"images": [b64(png_bytes())], field: value}
        response = client.post("/embed/image", json=payload)
        assert response.status_code == 400, field
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"]["fields"] == [field]
    assert encoder.image_batches == []


def test_images_must_be_base64_strings(client: TestClient, encoder: FakeEncoder) -> None:
    cases = [
        {"images": []},
        {"images": "not-a-list"},
        {"images": [123]},
        {"images": [""]},
        {"images": ["   "]},
        {"images": ["not base64!!"]},
        {"images": [b64(b"")]},
        {},
    ]
    for payload in cases:
        response = client.post("/embed/image", json=payload)
        assert response.status_code == 400, payload
        assert "images" in response.json()["error"]["details"]["fields"]
    assert encoder.image_batches == []


def test_containers_are_sniffed_and_unknown_formats_are_rejected(
    client: TestClient, encoder: FakeEncoder
) -> None:
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 8
    webp = b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8 " + b"\x00" * 4
    gif = b"GIF89a" + b"\x00" * 10

    accepted = client.post("/embed/image", json={"images": [b64(jpeg), b64(webp), b64(gif)]})
    assert accepted.status_code == 200
    assert len(accepted.json()["embeddings"]) == 3

    rejected = client.post("/embed/image", json={"images": [b64(b"%PDF-1.7\n")]})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["details"]["fields"] == ["images"]
    assert "PNG" in rejected.json()["error"]["message"]
    assert encoder.image_batches[-1] == [jpeg, webp, gif]


def test_limits_come_from_configuration() -> None:
    settings = Settings.from_env({"EMBEDDING_MAX_IMAGES": "2", "EMBEDDING_MAX_IMAGE_BYTES": "1024"})
    encoder = FakeEncoder()
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    image = b64(png_bytes())
    with TestClient(app) as client:
        too_many = client.post("/embed/image", json={"images": [image] * 3})
        too_big = client.post("/embed/image", json={"images": [b64(png_bytes() + b"\x00" * 1024)]})
        ok = client.post("/embed/image", json={"images": [image] * 2})
    assert too_many.status_code == 400
    assert "2" in too_many.json()["error"]["message"]
    assert too_big.status_code == 400
    assert "1024" in too_big.json()["error"]["message"]
    assert ok.status_code == 200
    assert len(encoder.image_batches) == 1


def test_model_must_match_when_present(client: TestClient, encoder: FakeEncoder) -> None:
    images = [b64(png_bytes())]
    mismatch = client.post("/embed/image", json={"images": images, "model": "other/model"})
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["details"]["fields"] == ["model"]

    match = client.post(
        "/embed/image",
        json={"images": images, "model": "google/embeddinggemma-2"},
    )
    assert match.status_code == 200


def test_vectors_are_normalized_and_shape_is_enforced(settings: Settings) -> None:
    raw = [3.0, 4.0, *([0.0] * 766)]
    encoder = FakeEncoder(vectors=[raw])
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed/image", json={"images": [b64(png_bytes())]})
    vector = response.json()["embeddings"][0]
    assert abs(norm(vector) - 1.0) < 1e-9
    assert abs(vector[0] - 0.6) < 1e-9

    for broken in ([[1.0, 0.0]], [[0.0] * 768]):
        encoder = FakeEncoder(vectors=broken)
        app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
        with TestClient(app) as client:
            failed = client.post("/embed/image", json={"images": [b64(png_bytes())]})
        assert failed.status_code == 502
        assert failed.json()["error"]["code"] == "upstream_failed"


def test_timeout_and_encoder_failure(settings: Settings) -> None:
    for error, status, code in (
        (UpstreamTimeout("slow"), 504, "upstream_timeout"),
        (UpstreamFailed("broken"), 502, "upstream_failed"),
    ):
        encoder = FakeEncoder(error=error)
        app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
        with TestClient(app) as client:
            response = client.post("/embed/image", json={"images": [b64(png_bytes())]})
        assert response.status_code == status
        assert response.json()["error"]["code"] == code


def test_request_id_is_echoed(client: TestClient, encoder: FakeEncoder) -> None:
    request_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    response = client.post(
        "/embed/image",
        json={"images": [b64(png_bytes())]},
        headers={"X-Request-Id": request_id},
    )
    assert response.headers["X-Request-Id"] == request_id
    assert encoder.request_ids == [request_id]


def test_llama_encoder_uses_the_marker_the_server_publishes() -> None:
    props_calls: list[str] = []
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            props_calls.append(request.url.path)
            return httpx.Response(200, json={"media_marker": "<__media_nonce__>"})
        bodies.append(json.loads(request.read().decode()))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": unit_vector(0)}]})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8092")
    encoder = LlamaEncoder("http://127.0.0.1:8092", 30, client=client)
    image = png_bytes()
    encoder.embed_images([image])
    encoder.embed_images([image])
    encoder.close()

    assert len(props_calls) == 1
    assert len(bodies) == 2
    for body in bodies:
        item = body["input"][0]
        assert item["prompt_string"] == "<__media_nonce__>"
        assert item["multimodal_data"] == [b64(image)]
        assert body["encoding_format"] == "float"


def test_llama_encoder_falls_back_to_the_default_marker() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            return httpx.Response(200, json={"build_info": "b1", "modalities": {"vision": True}})
        body = json.loads(request.read().decode())
        sent.append(body["input"][0]["prompt_string"])
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": unit_vector(0)}]})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8092")
    encoder = LlamaEncoder("http://127.0.0.1:8092", 30, client=client)
    assert encoder.embed_images([png_bytes()]) == [unit_vector(0)]
    encoder.close()
    assert sent == ["<__media__>"]


def test_bad_image_payload_is_an_upstream_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            return httpx.Response(200, json={"media_marker": "<__media__>"})
        return httpx.Response(500, json={"error": {"message": "no multimodal support"}})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8092")
    encoder = LlamaEncoder("http://127.0.0.1:8092", 30, client=client)
    with pytest.raises(UpstreamFailed):
        encoder.embed_images([png_bytes()])
    encoder.close()
