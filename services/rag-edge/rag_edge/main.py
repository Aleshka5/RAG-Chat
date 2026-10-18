"""ASGI app. GET /health is answered here; every other path is proxied."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

from rag_edge.config import Settings, load_settings
from rag_edge.observability import configure_logging
from rag_edge.proxy import build_client, proxy_request, request_id_from_header

logger = logging.getLogger("rag-edge")

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HEALTH_BODY = b'{"status":"ok"}'


def health_response(request: Request) -> Response:
    request_id = request_id_from_header(request.headers.get("x-request-id"))
    logger.debug("health", extra={"request_id": request_id})
    return Response(
        content=HEALTH_BODY,
        media_type="application/json",
        headers={"X-Request-Id": request_id},
    )


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(app.state.settings.log_level)
        app.state.client = build_client()
        logger.info(
            "listening on port %s max_upload_bytes=%s",
            app.state.settings.rag_edge_port,
            app.state.settings.max_upload_bytes,
        )
        try:
            yield
        finally:
            await app.state.client.aclose()

    app = FastAPI(
        title="rag-edge",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.get("/health")
    async def health(request: Request) -> Response:
        return health_response(request)

    @app.api_route("/", methods=_METHODS)
    async def root(request: Request) -> Response:
        return await proxy_request(request)

    @app.api_route("/{path:path}", methods=_METHODS)
    async def prefixed(request: Request, path: str) -> Response:
        del path
        return await proxy_request(request)

    return app


app = create_app(load_settings())


def main() -> None:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.rag_edge_port,
        access_log=False,
        log_config=None,
        log_level=settings.log_level,
    )
