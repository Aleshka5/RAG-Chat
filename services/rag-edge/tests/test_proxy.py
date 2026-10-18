import asyncio
import logging
import socket
from uuid import UUID

import httpx
import pytest
from rag_edge.config import Settings
from rag_edge.main import create_app
from rag_edge.observability import JsonFormatter
from tests.harness import Upstream, start_server, stop_server

USER_ID = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
FILE_ID = "11111111-1111-4111-8111-111111111111"
CHAT_ID = "b7e1a2c4-1111-4222-8333-444455556666"


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    for key, value in headers:
        if key.lower() == name.lower():
            return value
    return None


@pytest.fixture
async def stack():
    files = Upstream()
    chat = Upstream()
    frontend = Upstream()
    files_server = await start_server(files)
    chat_server = await start_server(chat)
    frontend_server = await start_server(frontend)
    app = create_app(
        Settings(
            file_collector_url=files_server.url,
            chat_url=chat_server.url,
            frontend_url=frontend_server.url,
            max_upload_bytes=524_288_000,
        )
    )
    edge = await start_server(app)
    client = httpx.AsyncClient(base_url=edge.url, timeout=httpx.Timeout(5.0, read=None))
    try:
        yield {
            "client": client,
            "files": files,
            "chat": chat,
            "frontend": frontend,
        }
    finally:
        await client.aclose()
        await stop_server(edge)
        await stop_server(files_server)
        await stop_server(chat_server)
        await stop_server(frontend_server)


async def test_routes_files_chats_and_frontend(stack: dict) -> None:
    client: httpx.AsyncClient = stack["client"]
    cases = [
        ("GET", "/api/files?limit=1&offset=0", "files", "/api/files", "limit=1&offset=0"),
        ("GET", f"/api/files/{FILE_ID}/content", "files", f"/api/files/{FILE_ID}/content", ""),
        ("POST", "/api/chats", "chat", "/api/chats", ""),
        ("POST", f"/api/chats/{CHAT_ID}/messages", "chat", f"/api/chats/{CHAT_ID}/messages", ""),
        ("GET", "/", "frontend", "/", ""),
        ("GET", "/assets/app.js", "frontend", "/assets/app.js", ""),
        ("GET", "/api/files-other", "frontend", "/api/files-other", ""),
    ]
    for method, url, role, path, query in cases:
        response = await client.request(method, url)
        assert response.status_code == 200, url
        recorded = stack[role].requests[-1]
        assert recorded["path"] == path
        assert recorded["query"] == query
        assert recorded["method"] == method


async def test_forwards_auth_and_request_headers(stack: dict) -> None:
    client: httpx.AsyncClient = stack["client"]
    request_id = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
    response = await client.get(
        "/api/files",
        headers={
            "X-Auth-User-Id": USER_ID,
            "X-Auth-Role": "BLOCKED",
            "X-Request-Id": request_id,
            "Accept": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id.lower()
    headers = stack["files"].requests[-1]["headers"]
    assert _header(headers, "x-auth-user-id") == USER_ID
    assert _header(headers, "x-auth-role") == "BLOCKED"
    assert _header(headers, "x-request-id") == request_id.lower()
    assert _header(headers, "accept") == "application/json"


async def test_generates_request_id_when_missing(stack: dict) -> None:
    client: httpx.AsyncClient = stack["client"]
    response = await client.get(
        "/api/chats",
        headers={"X-Auth-User-Id": USER_ID, "X-Auth-Role": "USER"},
    )
    generated = response.headers["x-request-id"]
    UUID(generated)
    headers = stack["chat"].requests[-1]["headers"]
    assert _header(headers, "x-request-id") == generated
    assert _header(headers, "x-auth-user-id") == USER_ID
    assert _header(headers, "x-auth-role") == "USER"


async def test_upload_body_is_streamed_and_not_rejected(stack: dict) -> None:
    client: httpx.AsyncClient = stack["client"]
    payload = b"%PDF-" + (b"a" * (1024 * 1024 + 100))
    response = await client.post(
        "/api/files",
        content=payload,
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "X-Auth-User-Id": USER_ID,
            "X-Auth-Role": "USER",
        },
    )
    assert response.status_code == 200
    assert stack["files"].requests[-1]["body"] == payload


async def test_file_collector_413_passes_through(stack: dict) -> None:
    async def too_large(scope, send, body):
        del scope, body
        raw = b'{"error":{"code":"file_too_large","message":"File exceeds the size limit"}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": raw})

    stack["files"].handler = too_large
    client: httpx.AsyncClient = stack["client"]
    response = await client.post("/api/files", content=b"%PDF-1.7")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


async def test_redirect_is_not_followed(stack: dict) -> None:
    async def redirect(scope, send, body):
        del scope, body
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", b"/files")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    stack["frontend"].handler = redirect
    client: httpx.AsyncClient = stack["client"]
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/files"


async def test_sse_is_flushed_before_the_upstream_finishes(stack: dict) -> None:
    gate = asyncio.Event()

    async def sse(scope, send, body):
        del scope, body
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream; charset=utf-8"),
                    (b"cache-control", b"no-cache"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'event: meta\ndata: {"sources":[]}\n\n',
                "more_body": True,
            }
        )
        await gate.wait()
        await send(
            {
                "type": "http.response.body",
                "body": b'event: done\ndata: {"finish_reason":"stop"}\n\n',
                "more_body": False,
            }
        )

    stack["chat"].handler = sse
    client: httpx.AsyncClient = stack["client"]
    async with client.stream(
        "POST",
        f"/api/chats/{CHAT_ID}/messages",
        content=b'{"content":"hi"}',
        headers={
            "Content-Type": "application/json",
            "X-Auth-User-Id": USER_ID,
            "X-Auth-Role": "USER",
            "Accept": "text/event-stream",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"
        chunks = response.aiter_bytes()
        first = await asyncio.wait_for(chunks.__anext__(), timeout=2)
        assert b"event: meta" in first
        assert not gate.is_set()
        gate.set()
        rest = bytearray()
        while True:
            try:
                rest.extend(await asyncio.wait_for(chunks.__anext__(), timeout=2))
            except StopAsyncIteration:
                break
        assert b"event: done" in rest
    headers = stack["chat"].requests[-1]["headers"]
    assert _header(headers, "x-auth-user-id") == USER_ID
    assert _header(headers, "x-auth-role") == "USER"
    UUID(_header(headers, "x-request-id") or "")


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_upstream_down_is_dependency_unavailable() -> None:
    closed = f"http://127.0.0.1:{_closed_port()}"
    app = create_app(
        Settings(
            file_collector_url=closed,
            chat_url=closed,
            frontend_url=closed,
        )
    )
    edge = await start_server(app)
    try:
        async with httpx.AsyncClient(base_url=edge.url, timeout=5.0) as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            response = await client.get("/api/files")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "dependency_unavailable"
        UUID(response.headers["x-request-id"])
    finally:
        await stop_server(edge)


async def test_logs_do_not_include_request_body(
    stack: dict, caplog: pytest.LogCaptureFixture
) -> None:
    log = logging.getLogger("rag-edge")
    log.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="rag-edge")
    client: httpx.AsyncClient = stack["client"]
    secret = "pdf-bytes-must-not-be-logged"
    await client.post("/api/files", content=secret.encode())
    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert secret not in rendered
    assert '"service": "rag-edge"' in rendered
    assert "request_id" in rendered
