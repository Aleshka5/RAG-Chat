from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from tests.fakes import FakeCounter, FakeEncoder


def test_default_batch_limit_is_16() -> None:
    settings = Settings.from_env({})
    assert settings.batch_size == 16
    assert settings.max_tokens == 1024
    assert settings.dimension == 768
    assert settings.model == "google/embeddinggemma-2"
    assert settings.port == 8091


def test_sixteen_texts_are_accepted_and_seventeen_are_rejected(
    client: TestClient, encoder: FakeEncoder
) -> None:
    accepted = client.post(
        "/embed",
        json={"texts": [f"chunk {index}" for index in range(16)], "input_type": "query"},
    )
    assert accepted.status_code == 200
    assert len(accepted.json()["embeddings"]) == 16
    assert len(encoder.seen) == 1
    assert len(encoder.seen[0]) == 16

    rejected = client.post(
        "/embed",
        json={"texts": [f"chunk {index}" for index in range(17)], "input_type": "query"},
    )
    assert rejected.status_code == 400
    body = rejected.json()
    assert body["error"]["code"] == "validation_error"
    assert "16" in body["error"]["message"]
    assert len(encoder.seen) == 1


def test_batch_limit_comes_from_configuration() -> None:
    settings = Settings.from_env({"EMBEDDING_BATCH_SIZE": "2"})
    encoder = FakeEncoder()
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        ok = client.post("/embed", json={"texts": ["one", "two"], "input_type": "query"})
        limited = client.post(
            "/embed", json={"texts": ["one", "two", "three"], "input_type": "query"}
        )
    assert ok.status_code == 200
    assert limited.status_code == 400
    assert "2" in limited.json()["error"]["message"]
    assert encoder.seen == [
        ["task: question answering | query: one", "task: question answering | query: two"]
    ]
