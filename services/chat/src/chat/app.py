import json
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from chat.auth import AuthMiddleware, request_id_of, user_id_of
from chat.config import Settings
from chat.embedding import EmbeddingClient
from chat.errors import ChatError, DependencyUnavailable, ValidationFailed, error_response
from chat.llm import LLMClient
from chat.repository import MongoChatRepository
from chat.service import ChatService, chat_payload, image_search_payload, message_payload
from chat.textutil import DEFAULT_TITLE, canonical_uuid
from chat.vectors import QdrantVectorIndex


def create_app(
    settings: Settings,
    repo: object | None = None,
    vectors: object | None = None,
    embedder: object | None = None,
    llm: object | None = None,
    clock: object | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        created: list[object] = []
        if app.state.repo is None:
            app.state.repo = MongoChatRepository(settings)
            created.append(app.state.repo)
        await app.state.repo.ensure_indexes()
        if app.state.vectors is None:
            app.state.vectors = QdrantVectorIndex(settings)
            created.append(app.state.vectors)
        if app.state.embedder is None:
            app.state.embedder = EmbeddingClient(settings)
            created.append(app.state.embedder)
        if app.state.llm is None:
            app.state.llm = LLMClient(settings)
            created.append(app.state.llm)
        if app.state.service is None:
            app.state.service = ChatService(
                settings,
                app.state.repo,
                app.state.vectors,
                app.state.embedder,
                app.state.llm,
                clock=app.state.clock,
            )
        try:
            yield
        finally:
            for resource in created:
                close = getattr(resource, "close", None)
                if close is not None:
                    await close()

    app = FastAPI(title="Chat", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.repo = repo
    app.state.vectors = vectors
    app.state.embedder = embedder
    app.state.llm = llm
    app.state.clock = clock
    if None not in (repo, vectors, embedder, llm):
        app.state.service = ChatService(
            settings,
            repo,
            vectors,
            embedder,
            llm,
            clock=clock,
        )
    else:
        app.state.service = None

    app.add_middleware(AuthMiddleware)
    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/api/chats", create_chat, methods=["POST"])
    app.add_api_route("/api/chats", list_chats, methods=["GET"])
    app.add_api_route("/api/chats/image-search", image_search, methods=["GET"])
    app.add_api_route("/api/chats/{chat_id}", get_chat, methods=["GET"])
    app.add_api_route("/api/chats/{chat_id}", delete_chat, methods=["DELETE"])
    app.add_api_route("/api/chats/{chat_id}/messages", create_message, methods=["POST"])
    return app


async def health() -> dict[str, str]:
    return {"status": "ok"}


async def create_chat(request: Request) -> JSONResponse:
    try:
        title = _parse_create_chat(await request.body())
        chat = await _service(request).create_chat(user_id_of(request), title)
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    return JSONResponse(status_code=201, content=chat_payload(chat))


async def list_chats(request: Request) -> JSONResponse:
    try:
        limit, offset = _parse_limit_offset(request.query_params, limit_default=50, limit_max=100)
        items, total = await _service(request).list_chats(user_id_of(request), limit, offset)
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    return JSONResponse(
        content={
            "items": [chat_payload(item) for item in items],
            "limit": limit,
            "offset": offset,
            "total": total,
        }
    )


async def image_search(request: Request) -> JSONResponse:
    try:
        query, limit, offset = _parse_image_search(request.query_params)
        matches = await _service(request).search_image_matches(
            user_id=user_id_of(request),
            query=query,
            limit=limit,
            offset=offset,
            request_id=request_id_of(request),
        )
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    return JSONResponse(content=image_search_payload(matches, limit, offset))


async def get_chat(request: Request, chat_id: str) -> JSONResponse:
    try:
        canonical = _require_chat_id(chat_id)
        limit, offset = _parse_limit_offset(request.query_params, limit_default=50, limit_max=200)
        chat, messages, total = await _service(request).list_messages(
            user_id_of(request), canonical, limit, offset
        )
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    body = chat_payload(chat)
    body.update(
        {
            "messages": [message_payload(item) for item in messages],
            "limit": limit,
            "offset": offset,
            "total_messages": total,
        }
    )
    return JSONResponse(content=body)


async def delete_chat(request: Request, chat_id: str) -> Response:
    try:
        canonical = _require_chat_id(chat_id)
        await _service(request).delete_chat(user_id_of(request), canonical)
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    return Response(status_code=204)


async def create_message(request: Request, chat_id: str) -> Response:
    try:
        canonical = _require_chat_id(chat_id)
        content, mode = _parse_message(await request.body())
        session = await _service(request).open_answer(
            user_id=user_id_of(request),
            chat_id=canonical,
            content=content,
            request_id=request_id_of(request),
            mode=mode,
        )
    except ChatError as exc:
        return error_response(exc, request_id_of(request))
    return StreamingResponse(
        _service(request).iter_sse(session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _service(request: Request) -> ChatService:
    service = request.app.state.service
    if service is None:
        raise DependencyUnavailable()
    return service


def _require_chat_id(chat_id: str) -> str:
    canonical = canonical_uuid(chat_id)
    if canonical is None:
        raise ValidationFailed(["chat_id"])
    return canonical


def _parse_limit_offset(
    params: Mapping[str, str], *, limit_default: int, limit_max: int
) -> tuple[int, int]:
    fields: list[str] = []
    limit = limit_default
    offset = 0
    if "limit" in params:
        raw = params["limit"]
        if raw.isdigit() and 1 <= int(raw) <= limit_max:
            limit = int(raw)
        else:
            fields.append("limit")
    if "offset" in params:
        raw = params["offset"]
        if raw.isdigit():
            offset = int(raw)
        else:
            fields.append("offset")
    if fields:
        raise ValidationFailed(fields)
    return limit, offset


def _parse_create_chat(raw: bytes) -> str:
    if not raw.strip():
        return DEFAULT_TITLE
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(["body"]) from exc
    if not isinstance(data, dict):
        raise ValidationFailed(["body"])
    if "title" not in data:
        return DEFAULT_TITLE
    title = data["title"]
    if not isinstance(title, str):
        raise ValidationFailed(["title"])
    title = title.strip()
    if not title or len(title) > 80:
        raise ValidationFailed(["title"])
    return title


def _parse_image_search(params: Mapping[str, str]) -> tuple[str, int, int]:
    fields: list[str] = []
    query = ""
    if "q" not in params:
        fields.append("q")
    else:
        query = params["q"].strip()
        if not query or len(query) > 4000:
            fields.append("q")
    limit = 20
    offset = 0
    if "limit" in params:
        raw_limit = params["limit"]
        if raw_limit.isdigit() and 1 <= int(raw_limit) <= 50:
            limit = int(raw_limit)
        else:
            fields.append("limit")
    if "offset" in params:
        raw_offset = params["offset"]
        if raw_offset.isdigit():
            offset = int(raw_offset)
        else:
            fields.append("offset")
    if fields:
        raise ValidationFailed(fields)
    return query, limit, offset


_MESSAGE_MODES = {"documents", "images"}


def _parse_message(raw: bytes) -> tuple[str, str]:
    if not raw.strip():
        raise ValidationFailed(["content"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(["body"]) from exc
    if not isinstance(data, dict):
        raise ValidationFailed(["body"])
    fields: list[str] = []
    content = ""
    if "content" not in data or not isinstance(data["content"], str):
        fields.append("content")
    else:
        content = data["content"].strip()
        if not content or len(content) > 4000:
            fields.append("content")
    mode = "documents"
    if "mode" in data:
        raw_mode = data["mode"]
        if raw_mode not in _MESSAGE_MODES:
            fields.append("mode")
        else:
            mode = raw_mode
    if fields:
        raise ValidationFailed(fields)
    return content, mode
