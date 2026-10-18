import math

from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from embedding.errors import UpstreamFailed, UpstreamTimeout
from tests.fakes import FakeCounter, FakeEncoder


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def test_response_vectors_match_texts_and_are_768(client: TestClient) -> None:
    response = client.post(
        "/embed",
        json={"texts": ["first", "second"], "input_type": "query"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "google/embeddinggemma-2"
    assert body["dimension"] == 768
    assert len(body["embeddings"]) == 2
    assert len(body["embeddings"][0]) == 768
    assert len(body["embeddings"][1]) == 768
    assert body["embeddings"][0][0] == 1.0
    assert body["embeddings"][1][1] == 1.0
    assert abs(_norm(body["embeddings"][0]) - 1.0) < 1e-6
    assert abs(_norm(body["embeddings"][1]) - 1.0) < 1e-6


def test_non_unit_vector_is_l2_normalized(settings: Settings) -> None:
    raw = [3.0, 4.0, *([0.0] * 766)]
    encoder = FakeEncoder(vectors=[raw])
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": ["chunk"], "input_type": "query"})
    assert response.status_code == 200
    vector = response.json()["embeddings"][0]
    assert len(vector) == 768
    assert abs(vector[0] - 0.6) < 1e-9
    assert abs(vector[1] - 0.8) < 1e-9
    assert abs(_norm(vector) - 1.0) < 1e-9


def test_wrong_shape_nan_and_zero_are_upstream_failures(settings: Settings) -> None:
    cases: list[list[list[float]]] = [
        [[1.0, 0.0]],
        [[float("nan"), *([0.0] * 767)]],
        [[float("inf"), *([0.0] * 767)]],
        [[0.0] * 768],
        [],
    ]
    for vectors in cases:
        encoder = FakeEncoder(vectors=vectors)
        app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
        with TestClient(app) as client:
            response = client.post("/embed", json={"texts": ["chunk"], "input_type": "query"})
        assert response.status_code == 502, vectors
        assert response.json()["error"]["code"] == "upstream_failed"


def test_timeout_is_504(settings: Settings) -> None:
    encoder = FakeEncoder(error=UpstreamTimeout("Embedding timed out"))
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": ["chunk"], "input_type": "query"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


def test_encoder_failure_is_502(settings: Settings) -> None:
    encoder = FakeEncoder(error=UpstreamFailed("Embedding upstream failed"))
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.post("/embed", json={"texts": ["chunk"], "input_type": "query"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_failed"
