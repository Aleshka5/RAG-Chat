import pytest
from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from tests.fakes import FakeCounter, FakeEncoder


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env({})


@pytest.fixture
def encoder() -> FakeEncoder:
    return FakeEncoder()


@pytest.fixture
def counter() -> FakeCounter:
    return FakeCounter(1)


@pytest.fixture
def client(settings: Settings, encoder: FakeEncoder, counter: FakeCounter):
    app = create_app(settings, encoder=encoder, token_counter=counter)
    with TestClient(app) as test_client:
        yield test_client
