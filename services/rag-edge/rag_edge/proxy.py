"""Stream requests to file-collector, chat, or the frontend without buffering SSE."""

import logging
import re
from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.datastructures import Headers

from rag_edge.config import Settings

logger = logging.getLogger("rag-edge")

# Hop-by-hop headers are not forwarded. Content-Length is dropped only on the
# request: the body is streamed and httpx sets the framing. The response keeps
# Content-Length so PDF downloads stay sized.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}
_REQUEST_DROP = _HOP_BY_HOP | {"content-length"}

_FILE_ID = re.compile(r"^/api/files/([^/]+)")
_CHAT_ID = re.compile(r"^/api/chats/([^/]+)")


def select_upstream(path: str, settings: Settings) -> str:
    if path == "/api/files" or path.startswith("/api/files/"):
        return settings.file_collector_url
    if path == "/api/chats" or path.startswith("/api/chats/"):
        return settings.chat_url
    return settings.frontend_url


def upstream_role(base: str, settings: Settings) -> str:
    if base == settings.file_collector_url:
        return "file-collector"
    if base == settings.chat_url:
        return "chat"
    if base == settings.frontend_url:
        return "frontend"
    return "upstream"


def canonical_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value.strip()))
    except ValueError:
        return None


def request_id_from_header(value: str | None) -> str:
    parsed = canonical_uuid(value.split(",")[0] if value else None)
    if parsed is not None:
        return parsed
    return str(uuid4())


def path_ids(path: str) -> dict[str, str]:
    found: dict[str, str] = {}
    file_match = _FILE_ID.match(path)
    chat_match = _CHAT_ID.match(path)
    if file_match is not None:
        file_id = canonical_uuid(file_match.group(1))
        if file_id is not None:
            found["file_id"] = file_id
    if chat_match is not None:
        chat_id = canonical_uuid(chat_match.group(1))
        if chat_id is not None:
            found["chat_id"] = chat_id
    return found


def build_upstream_url(base: str, request: Request) -> str:
    raw_path = request.scope.get("raw_path") or request.url.path.encode("ascii", "ignore")
    if isinstance(raw_path, str):
        raw_path = raw_path.encode("ascii", "ignore")
    if not raw_path.startswith(b"/"):
        raw_path = b"/" + raw_path
    query = request.scope.get("query_string") or b""
    target = base.encode("ascii") + raw_path
    if query:
        target += b"?" + query
    return target.decode("latin-1")


def _connection_tokens(headers: Iterable[tuple[str, str]]) -> set[str]:
    tokens: set[str] = set()
    for name, value in headers:
        if name.lower() != "connection":
            continue
        tokens.update(part.strip().lower() for part in value.split(",") if part.strip())
    return tokens


def _decode_raw(raw: Iterable[tuple[bytes, bytes]]) -> list[tuple[str, str]]:
    return [(name.decode("latin-1"), value.decode("latin-1")) for name, value in raw]


def outgoing_request_headers(
    raw_headers: Iterable[tuple[str, str]],
    request_id: str,
) -> list[tuple[str, str]]:
    headers = list(raw_headers)
    drop = set(_REQUEST_DROP)
    drop.update(_connection_tokens(headers))
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        if name.lower() in drop or name.lower() == "x-request-id":
            continue
        forwarded.append((name, value))
    forwarded.append(("X-Request-Id", request_id))
    return forwarded


def outgoing_response_headers(
    raw_headers: Iterable[tuple[str, str]],
    request_id: str,
) -> list[tuple[str, str]]:
    headers = list(raw_headers)
    drop = set(_HOP_BY_HOP)
    drop.update(_connection_tokens(headers))
    drop.add("x-request-id")
    forwarded: list[tuple[str, str]] = []
    content_type = ""
    for name, value in headers:
        if name.lower() in drop:
            continue
        if name.lower() == "content-type":
            content_type = value
        forwarded.append((name, value))
    if content_type.split(";", 1)[0].strip().lower() == "text/event-stream":
        # Ask any intermediary not to accumulate the chat stream.
        forwarded.append(("X-Accel-Buffering", "no"))
        if not any(name.lower() == "cache-control" for name, _ in forwarded):
            forwarded.append(("Cache-Control", "no-cache"))
    forwarded.append(("X-Request-Id", request_id))
    return forwarded


def _header_object(pairs: list[tuple[str, str]]) -> Headers:
    return Headers(raw=[(name.encode("latin-1"), value.encode("latin-1")) for name, value in pairs])


def _has_request_body(request: Request) -> bool:
    if request.method in {"GET", "HEAD"}:
        return False
    if request.headers.get("transfer-encoding"):
        return True
    length = request.headers.get("content-length")
    if length is None:
        return request.method in {"POST", "PUT", "PATCH"}
    try:
        return int(length) > 0
    except ValueError:
        return True


def _log_extra(request_id: str, user_id: str | None, ids: dict[str, str]) -> dict[str, str]:
    extra = {"request_id": request_id}
    if user_id:
        extra["user_id"] = user_id
    extra.update(ids)
    return extra


def dependency_unavailable(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "dependency_unavailable",
                "message": "Dependency unavailable",
            }
        },
        headers={"X-Request-Id": request_id},
    )


def build_client() -> httpx.AsyncClient:
    # read=None: a chat stream is not cut or held back by an edge timeout.
    # trust_env=False: internal DNS names must not go out through HTTP_PROXY.
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=None, write=None, pool=5.0),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
    )


async def proxy_request(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.client
    request_id = request_id_from_header(request.headers.get("x-request-id"))
    path = request.url.path
    base = select_upstream(path, settings)
    role = upstream_role(base, settings)
    user_id = canonical_uuid(request.headers.get("x-auth-user-id"))
    ids = path_ids(path)
    extra = _log_extra(request_id, user_id, ids)
    # settings.max_upload_bytes is the shared ceiling with File Collector.
    # The edge does not apply a smaller body cap and does not answer 413.
    try:
        upstream_request = client.build_request(
            request.method,
            build_upstream_url(base, request),
            headers=outgoing_request_headers(_decode_raw(request.headers.raw), request_id),
            content=request.stream() if _has_request_body(request) else None,
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError:
        logger.warning("upstream unavailable", extra=extra)
        return dependency_unavailable(request_id)

    response_headers = outgoing_response_headers(upstream.headers.multi_items(), request_id)
    logger.info("%s %s -> %s %s", request.method, path, role, upstream.status_code, extra=extra)

    async def iterate() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        iterate(),
        status_code=upstream.status_code,
        headers=_header_object(response_headers),
    )
