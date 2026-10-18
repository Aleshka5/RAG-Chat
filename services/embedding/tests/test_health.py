from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from tests.fakes import FakeCounter, FakeEncoder


def test_health_is_ok_when_the_model_is_loaded(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_ok_before_the_model_is_ready(settings: Settings) -> None:
    encoder = FakeEncoder(healthy=False)
    app = create_app(settings, encoder=encoder, token_counter=FakeCounter(1))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert response.json().get("status") != "ok"
