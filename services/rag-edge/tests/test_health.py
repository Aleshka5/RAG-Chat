import json
from uuid import UUID

import httpx
import pytest
from rag_edge.config import Settings
from rag_edge.main import HEALTH_BODY, create_app


@pytest.fixture
async def edge_client():
    app = create_app(
        Settings(
            file_collector_url="http://127.0.0.1:9",
            chat_url="http://127.0.0.1:9",
            frontend_url="http://127.0.0.1:9",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://rag-edge") as client:
        yield client


async def test_health_is_public_and_does_not_call_upstreams(edge_client: httpx.AsyncClient) -> None:
    response = await edge_client.get("/health")
    assert response.status_code == 200
    assert response.content == HEALTH_BODY
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"].startswith("application/json")
    UUID(response.headers["x-request-id"])


async def test_health_returns_the_request_id_it_accepted(edge_client: httpx.AsyncClient) -> None:
    request_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    response = await edge_client.get("/health", headers={"X-Request-Id": request_id.upper()})
    assert response.headers["x-request-id"] == request_id
    assert json.loads(response.content) == {"status": "ok"}
