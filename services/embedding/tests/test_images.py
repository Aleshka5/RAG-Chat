import base64
import json
import math
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from embedding.encoder import ImageInput, LlamaEncoder
from embedding.errors import UpstreamFailed, UpstreamTimeout, ValidationFailed
from embedding.request import sniff_media_type
from embedding.vectors import project_embeddings
from tests.fakes import FakeCounter, FakeEncoder

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"
_WEBP = b"RIFF\x24\x00\x00\x00WEBP"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


PNG = _b64(_PNG)
JPEG = _b64(_JPEG)
GIF87 = _b64(_GIF87)
GIF89 = _b64(_GIF89)
WEBP = _b64(_WEBP)


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (_JPEG + b"\xe0", "image/jpeg"),
        (_PNG, "image/png"),
        (_GIF87, "image/gif"),
        (_GIF89 + b"payload", "image/gif"),
        (_WEBP + b"VP8 ", "image/webp"),
    ],
)
def test_sniff_accepts_container_magic(data: bytes, media_type: str) -> None:
    assert sniff_media_type(data) == media_type


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff\xd8",
        b"\xff\xd8\xfe",
        b"\x89PNG\r\n\x1a",
        b"GIF90a",
        b"RIFF\x00\x00\x00\x00WAVE",
        b"BM",
        b"%PDF",
    ],
)
def test_sniff_rejects_other_magic(data: bytes) -> None:
    with pytest.raises(ValidationFailed) as captured:
        sniff_media_type(data)
    assert captured.value.fields == ["images"]


def test_image_count_accepts_one_through_four_and_rejects_zero_and_five(
    client: TestClient, encoder: FakeEncoder
) -> None:
    one = client.post("/embed/image", json={"images": [PNG]})
    assert one.status_code == 200
    assert len(one.json()["embeddings"]) == 1
    assert len(one.json()["embeddings"][0]) == 768

    four_images = [PNG, JPEG, GIF89, WEBP]
    four = client.post("/embed/image", json={"images": four_images})
    assert four.status_code == 200
    body = four.json()
    assert body["dimension"] == 768
    assert body["model"] == "google/embeddinggemma-2"
    assert len(body["embeddings"]) == 4
    assert [len(vector) for vector in body["embeddings"]] == [768, 768, 768, 768]
    assert body["embeddings"][0][0] == 1.0
    assert body["embeddings"][3][3] == 1.0
    assert encoder.image_seen[1] == [
        ImageInput("image/png", PNG),
        ImageInput("image/jpeg", JPEG),
        ImageInput("image/gif", GIF89),
        ImageInput("image/webp", WEBP),
    ]
    assert encoder.seen == []

    empty = client.post("/embed/image", json={"images": []})
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "validation_error"
    assert empty.json()["error"]["details"]["fields"] == ["images"]
    assert "4" in empty.json()["error"]["message"]

    five = client.post("/embed/image", json={"images": [PNG, JPEG, GIF87, GIF89, WEBP]})
    assert five.status_code == 400
    assert five.json()["error"]["code"] == "validation_error"
    assert five.json()["error"]["details"]["fields"] == ["images"]
    assert "4" in five.json()["error"]["message"]
    assert len(encoder.image_seen) == 2


def test_image_count_comes_from_configuration() -> None:
    settings = Settings.from_env({"EMBEDDING_MAX_IMAGES": "2"})
    encoder = FakeEncoder()
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        ok = client.post("/embed/image", json={"images": [PNG, JPEG]})
        limited = client.post("/embed/image", json={"images": [PNG, JPEG, GIF89]})
    assert ok.status_code == 200
    assert limited.status_code == 400
    assert "2" in limited.json()["error"]["message"]
    assert len(encoder.image_seen) == 1


@pytest.mark.parametrize(
    "image",
    ["@@@", "ab", "aGVs bG8=", "data:image/png;base64,aaaa", "", 1, None],
)
def test_bad_base64_is_validation_error(
    client: TestClient, encoder: FakeEncoder, image: object
) -> None:
    response = client.post("/embed/image", json={"images": [image]})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["fields"] == ["images"]
    assert encoder.image_seen == []


def test_oversize_decoded_image_is_rejected(encoder: FakeEncoder) -> None:
    settings = Settings.from_env({"EMBEDDING_MAX_IMAGE_BYTES": "12"})
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    exact = _b64(_PNG + b"\x00" * 4)
    over = _b64(_PNG + b"\x00" * 5)
    with TestClient(app) as client:
        accepted = client.post("/embed/image", json={"images": [exact]})
        rejected = client.post("/embed/image", json={"images": [over]})
    assert accepted.status_code == 200
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "validation_error"
    assert rejected.json()["error"]["details"]["fields"] == ["images"]
    assert "EMBEDDING_MAX_IMAGE_BYTES" in rejected.json()["error"]["message"]
    assert len(encoder.image_seen) == 1
    assert encoder.image_seen[0][0].base64_data == exact


def test_unsupported_magic_is_validation_error(client: TestClient, encoder: FakeEncoder) -> None:
    wave = _b64(b"RIFF\x00\x00\x00\x00WAVE")
    response = client.post("/embed/image", json={"images": [wave]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["fields"] == ["images"]
    assert encoder.image_seen == []


def test_text_of_valid_base64_is_unsupported_magic(
    client: TestClient, encoder: FakeEncoder
) -> None:
    response = client.post("/embed/image", json={"images": ["aGVsbG8="]})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == ["images"]
    assert response.json()["error"]["message"] == "unsupported image format"
    assert encoder.image_seen == []


@pytest.mark.parametrize("field", ["texts", "input_type", "title"])
def test_text_fields_are_rejected(client: TestClient, encoder: FakeEncoder, field: str) -> None:
    payload: dict[str, object] = {"images": [PNG], field: "query"}
    response = client.post("/embed/image", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["fields"] == [field]
    assert encoder.image_seen == []
    assert encoder.seen == []


def test_every_text_field_is_named(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post(
        "/embed/image",
        json={
            "images": [PNG],
            "title": "Отчёт.pdf",
            "texts": ["chunk"],
            "input_type": "document",
            "caption": "nope",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["fields"] == [
        "texts",
        "input_type",
        "title",
        "caption",
    ]
    assert encoder.image_seen == []


def test_missing_projector_returns_502_and_leaves_text_embed_healthy(settings: Settings) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        calls.append(request.read().decode())
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, *([0.0] * 767)]}]},
        )

    encoder = LlamaEncoder(
        "http://127.0.0.1:8092",
        30,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="http://127.0.0.1:8092",
        ),
        images_ready=False,
    )
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        image = client.post("/embed/image", json={"images": [PNG]})
        text = client.post("/embed", json={"texts": ["question"], "input_type": "query"})
        health = client.get("/health")
    assert image.status_code == 502
    assert image.json()["error"]["code"] == "upstream_failed"
    assert text.status_code == 200
    assert text.json()["dimension"] == 768
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert len(calls) == 1
    assert "image_url" not in calls[0]
    encoder.close()


def test_wrong_model_is_rejected(client: TestClient, encoder: FakeEncoder) -> None:
    mismatch = client.post(
        "/embed/image",
        json={"images": [PNG], "model": "other/model"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["details"]["fields"] == ["model"]
    assert "other/model" not in mismatch.text
    assert encoder.image_seen == []

    match = client.post(
        "/embed/image",
        json={"images": [PNG], "model": "google/embeddinggemma-2"},
    )
    assert match.status_code == 200
    assert match.json()["model"] == "google/embeddinggemma-2"


def test_image_vector_is_768_and_l2_normalised_by_the_projection_helper(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = [3.0, 4.0, *([0.0] * 766)]
    encoder = FakeEncoder(vectors=[raw])
    seen: dict[str, object] = {}
    real = project_embeddings

    def spy(values: object, count: int, dimension: int) -> list[list[float]]:
        seen["count"] = count
        seen["dimension"] = dimension
        seen["raw"] = values
        return real(values, count, dimension)

    monkeypatch.setattr("embedding.app.project_embeddings", spy)
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed/image", json={"images": [PNG]})
    assert response.status_code == 200
    body = response.json()
    assert body["dimension"] == 768
    vector = body["embeddings"][0]
    assert len(vector) == 768
    assert abs(vector[0] - 0.6) < 1e-9
    assert abs(vector[1] - 0.8) < 1e-9
    assert abs(_norm(vector) - 1.0) < 1e-9
    assert seen == {"count": 1, "dimension": 768, "raw": [raw]}


def test_image_request_id_is_echoed_or_generated(client: TestClient, encoder: FakeEncoder) -> None:
    request_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    response = client.post(
        "/embed/image",
        json={"images": [PNG]},
        headers={"X-Request-Id": request_id},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == request_id
    assert encoder.request_ids == [request_id]

    generated = client.post(
        "/embed/image",
        json={"images": [JPEG]},
        headers={"X-Request-Id": "not-a-uuid"},
    )
    assert generated.headers["X-Request-Id"] != "not-a-uuid"
    uuid.UUID(generated.headers["X-Request-Id"])


def test_image_upstream_decode_failure_is_502(settings: Settings) -> None:
    encoder = FakeEncoder(error=UpstreamFailed("failed to decode image"))
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed/image", json={"images": [PNG]})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_failed"


def test_image_timeout_is_504(settings: Settings) -> None:
    encoder = FakeEncoder(error=UpstreamTimeout("Embedding timed out"))
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed/image", json={"images": [PNG]})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


def test_llama_encoder_posts_image_content_without_a_text_prefix() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read())
        seen["request_id"] = request.headers.get("x-request-id")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8092")
    encoder = LlamaEncoder("http://127.0.0.1:8092", 30, client=client)
    vectors = encoder.embed_images(
        [ImageInput("image/png", PNG), ImageInput("image/jpeg", JPEG)],
        request_id="6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
    )
    assert seen["path"] == "/v1/embeddings"
    assert seen["request_id"] == "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    assert seen["body"] == {
        "input": [
            {
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{PNG}"},
                    }
                ]
            },
            {
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{JPEG}"},
                    }
                ]
            },
        ],
        "encoding_format": "float",
    }
    encoded = json.dumps(seen["body"])
    assert "task:" not in encoded
    assert "title:" not in encoded
    assert "prompt_string" not in encoded
    assert "input_audio" not in encoded
    assert '"type": "text"' not in encoded
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    encoder.close()


def test_llama_encoder_maps_image_decode_failure_and_timeout() -> None:
    def decode_failed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "failed to decode image"}})

    broken = LlamaEncoder(
        "http://127.0.0.1:8092",
        30,
        client=httpx.Client(
            transport=httpx.MockTransport(decode_failed),
            base_url="http://127.0.0.1:8092",
        ),
    )
    with pytest.raises(UpstreamFailed):
        broken.embed_images([ImageInput("image/png", PNG)])
    broken.close()

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    slow = LlamaEncoder(
        "http://127.0.0.1:8092",
        30,
        client=httpx.Client(
            transport=httpx.MockTransport(timeout),
            base_url="http://127.0.0.1:8092",
        ),
    )
    with pytest.raises(UpstreamTimeout):
        slow.embed_images([ImageInput("image/jpeg", JPEG)])
    slow.close()
