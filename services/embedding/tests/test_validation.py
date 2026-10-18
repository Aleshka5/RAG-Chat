import uuid

import pytest
from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from embedding.errors import ConfigError
from tests.fakes import FakeCounter, FakeEncoder


def test_query_rejects_title(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post(
        "/embed",
        json={
            "texts": ["What causes the northern lights?"],
            "input_type": "query",
            "title": "Отчёт.pdf",
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["fields"] == ["title"]
    assert encoder.seen == []


def test_query_rejects_null_title(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post(
        "/embed",
        json={"texts": ["question"], "input_type": "query", "title": None},
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == ["title"]
    assert encoder.seen == []


def test_document_requires_title(client: TestClient, encoder: FakeEncoder) -> None:
    response = client.post("/embed", json={"texts": ["chunk"], "input_type": "document"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["fields"] == ["title"]
    assert encoder.seen == []


def test_document_rejects_blank_title(client: TestClient) -> None:
    response = client.post(
        "/embed",
        json={"texts": ["chunk"], "input_type": "document", "title": "   "},
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == ["title"]


def test_input_type_is_required_and_exact(client: TestClient) -> None:
    missing = client.post("/embed", json={"texts": ["chunk"]})
    assert missing.status_code == 400
    assert missing.json()["error"]["details"]["fields"] == ["input_type"]

    wrong = client.post("/embed", json={"texts": ["chunk"], "input_type": "Document"})
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "validation_error"


def test_texts_must_be_non_empty_strings(client: TestClient, encoder: FakeEncoder) -> None:
    cases = [
        {"texts": [], "input_type": "query"},
        {"texts": "chunk", "input_type": "query"},
        {"texts": ["  "], "input_type": "query"},
        {"texts": [""], "input_type": "query"},
        {"texts": [1], "input_type": "query"},
        {"texts": [None], "input_type": "query"},
        {"input_type": "query"},
    ]
    for payload in cases:
        response = client.post("/embed", json=payload)
        assert response.status_code == 400, payload
        assert response.json()["error"]["code"] == "validation_error"
        assert "texts" in response.json()["error"]["details"]["fields"]
    assert encoder.seen == []


def test_model_must_match_when_present(client: TestClient, encoder: FakeEncoder) -> None:
    mismatch = client.post(
        "/embed",
        json={"texts": ["question"], "input_type": "query", "model": "other/model"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["details"]["fields"] == ["model"]
    assert "other/model" not in mismatch.text
    assert encoder.seen == []

    match = client.post(
        "/embed",
        json={"texts": ["question"], "input_type": "query", "model": "google/embeddinggemma-2"},
    )
    assert match.status_code == 200
    assert match.json()["model"] == "google/embeddinggemma-2"


def test_invalid_json_is_validation_error(client: TestClient) -> None:
    response = client.post(
        "/embed", content=b"not-json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_token_limit_rejects_without_truncation(settings: Settings) -> None:
    encoder = FakeEncoder()
    long_text = "северное сияние " * 80
    counter = FakeCounter(1025)
    app = create_app(settings, encoder=encoder, token_counter=counter)
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": [long_text], "input_type": "query"})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Token count exceeds EMBEDDING_MAX_TOKENS"
    assert encoder.seen == []
    assert counter.seen == [f"task: question answering | query: {long_text.strip()}"]


def test_token_limit_allows_exact_maximum_and_counts_each_prefixed_text(settings: Settings) -> None:
    encoder = FakeEncoder()

    def counts(text: str) -> int:
        return 1025 if text.endswith("too-long") else 1024

    counter = FakeCounter(counts)
    app = create_app(settings, encoder=encoder, token_counter=counter)
    with TestClient(app) as client:
        ok = client.post("/embed", json={"texts": ["fits"], "input_type": "query"})
        assert ok.status_code == 200
        too_long = client.post(
            "/embed",
            json={"texts": ["fits", "too-long"], "input_type": "query"},
        )
    assert too_long.status_code == 400
    assert encoder.seen == [["task: question answering | query: fits"]]
    assert "too-long" not in encoder.seen[0][0]


def test_request_id_is_echoed_or_generated(client: TestClient) -> None:
    request_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    response = client.post(
        "/embed",
        json={"texts": ["question"], "input_type": "query"},
        headers={"X-Request-Id": request_id},
    )
    assert response.headers["X-Request-Id"] == request_id

    generated = client.get("/health", headers={"X-Request-Id": "not-a-uuid"})
    assert generated.headers["X-Request-Id"] != "not-a-uuid"
    uuid.UUID(generated.headers["X-Request-Id"])

    missing = client.get("/health")
    uuid.UUID(missing.headers["X-Request-Id"])


def test_invalid_configuration_names_the_variable_only() -> None:
    with pytest.raises(ConfigError) as captured:
        Settings.from_env({"EMBEDDING_BATCH_SIZE": "nope"})
    assert captured.value.name == "EMBEDDING_BATCH_SIZE"
    assert "nope" not in str(captured.value)

    with pytest.raises(ConfigError) as weights:
        Settings.from_env({"EMBEDDING_GGUF": "mmproj-embeddinggemma-2-Q8_0.gguf"})
    assert weights.value.name == "EMBEDDING_GGUF"

    with pytest.raises(ConfigError) as f16:
        Settings.from_env({"EMBEDDING_GGUF": "embeddinggemma-2-F16.gguf"})
    assert f16.value.name == "EMBEDDING_GGUF"

    with pytest.raises(ConfigError) as exposed:
        Settings.from_env({"EMBEDDING_LLAMA_URL": "http://0.0.0.0:8092"})
    assert exposed.value.name == "EMBEDDING_LLAMA_URL"
    assert "0.0.0.0" not in str(exposed.value)
