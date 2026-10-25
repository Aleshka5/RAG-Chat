import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from embedding.config import Settings
from embedding.encoder import TextEncoder
from embedding.errors import UpstreamFailed, UpstreamTimeout, ValidationFailed
from embedding.loader import load_model
from embedding.request import parse_embed_request, parse_image_embed_request
from embedding.tokens import TokenCounter
from embedding.vectors import project_embeddings

log = logging.getLogger("embedding")

_REQUEST_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def create_app(
    settings: Settings | None = None,
    *,
    encoder: TextEncoder | None = None,
    token_counter: TokenCounter | None = None,
) -> FastAPI:
    """Build the embedding API.

    Production startup leaves ``encoder`` and ``token_counter`` empty. The
    lifespan then calls :func:`load_model`, which blocks until llama-server has
    loaded the GGUF. Inject both only from tests.
    """
    resolved = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.encoder is None or app.state.token_counter is None:
            loaded = load_model(app.state.settings)
            app.state.encoder = loaded.encoder
            app.state.token_counter = loaded.token_counter
        try:
            yield
        finally:
            close = getattr(app.state.encoder, "close", None)
            if close is not None:
                close()

    app = FastAPI(title="Embedding", version="1.0.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.encoder = encoder
    app.state.token_counter = token_counter

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = resolve_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(ValidationFailed)
    async def validation_failed(_request: Request, exc: ValidationFailed) -> JSONResponse:
        return error_response(400, "validation_error", exc.message, exc.fields)

    @app.get("/health")
    def health() -> JSONResponse:
        encoder_live = app.state.encoder
        healthy = encoder_live is not None and bool(encoder_live.healthy())
        if not healthy:
            return error_response(503, "dependency_unavailable", "Model is not loaded")
        return JSONResponse({"status": "ok"})

    @app.post("/embed")
    async def embed(request: Request) -> JSONResponse:
        current = request.app.state.settings
        parsed = parse_embed_request(await _read_json(request), current)
        for prefixed in parsed.prefixed:
            if request.app.state.token_counter.count(prefixed) > current.max_tokens:
                raise ValidationFailed("Token count exceeds EMBEDDING_MAX_TOKENS", ["texts"])

        def produce() -> list[list[float]]:
            return request.app.state.encoder.embed(
                parsed.prefixed,
                request_id=request.state.request_id,
            )

        return await _embedding_response(request, produce, len(parsed.prefixed))

    @app.post("/embed/image")
    async def embed_image(request: Request) -> JSONResponse:
        parsed = parse_image_embed_request(await _read_json(request), request.app.state.settings)

        def produce() -> list[list[float]]:
            return request.app.state.encoder.embed_images(
                parsed.images,
                request_id=request.state.request_id,
            )

        return await _embedding_response(request, produce, len(parsed.images))

    return app


def resolve_request_id(header: str | None) -> str:
    if header is not None and _REQUEST_ID.fullmatch(header.strip()):
        return header.strip()
    return str(uuid.uuid4())


async def _embedding_response(
    request: Request,
    produce: Callable[[], list[list[float]]],
    count: int,
) -> JSONResponse:
    current = request.app.state.settings
    try:
        raw = await asyncio.to_thread(produce)
        vectors = project_embeddings(raw, count, current.dimension)
    except UpstreamTimeout:
        log.warning("embedding timed out request_id=%s", request.state.request_id)
        return error_response(504, "upstream_timeout", "Embedding timed out")
    except UpstreamFailed as exc:
        log.warning(
            "embedding upstream failed request_id=%s",
            request.state.request_id,
        )
        log.debug("embedding upstream detail: %s", exc)
        return error_response(502, "upstream_failed", "Embedding upstream failed")
    return JSONResponse(
        {
            "embeddings": vectors,
            "model": current.model,
            "dimension": current.dimension,
        }
    )


def error_response(
    status: int,
    code: str,
    message: str,
    fields: list[str] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if fields is not None:
        error["details"] = {"fields": fields}
    return JSONResponse(status_code=status, content={"error": error})


async def _read_json(request: Request) -> object:
    body = await request.body()
    if not body:
        raise ValidationFailed("Invalid JSON", ["body"])
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ValidationFailed("Invalid JSON", ["body"]) from None
