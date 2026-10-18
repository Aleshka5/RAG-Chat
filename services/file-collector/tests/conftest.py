import pytest
from fastapi.testclient import TestClient
from tests.support import build_app


@pytest.fixture
def stack():
    app, files, objects, publisher = build_app()
    with TestClient(app) as client:
        yield client, files, objects, publisher
