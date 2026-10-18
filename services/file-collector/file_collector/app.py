"""FastAPI application factory."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from file_collector.api import parse_uuid, router
from file_collector.config import Settings
from file_collector.errors import ApiError, PublishError, StorageError, error_response
from file_collector.publisher import RabbitPublisher
from file_collector.repository import MongoFiles
from file_collector.storage import S3Objects

logger = logging.getLogger("file_collector")


def create_app(
    settings: Settings,
    *,
    files=None,
    objects=None,
    publisher=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app_arg: FastAPI):
        try:
            await app_arg.state.files.connect()
            await app_arg.state.objects.connect()
            await app_arg.state.publisher.connect()
            await app_arg.state.files.ensure_indexes()
            await app_arg.state.objects.ensure_bucket()
            await app_arg.state.publisher.ensure_topology()
        except Exception as exc:
            logger.error("startup initialization failed %s", type(exc).__name__)
            await _close(getattr(app_arg.state, "publisher", None))
            await _close(getattr(app_arg.state, "objects", None))
            await _close(getattr(app_arg.state, "files", None))
            raise
        logger.info("file collector ready")
        try:
            yield
        finally:
            await _close(app_arg.state.publisher)
            await _close(app_arg.state.objects)
            await _close(app_arg.state.files)

    app = FastAPI(title="File Collector", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.files = files if files is not None else MongoFiles(settings)
    app.state.objects = objects if objects is not None else S3Objects(settings)
    app.state.publisher = publisher if publisher is not None else RabbitPublisher(settings)
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StorageError)
    async def storage_error(request: Request, _exc: StorageError) -> JSONResponse:
        logger.error(
            "dependency unavailable",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return error_response(503, "dependency_unavailable", "Dependency unavailable")

    @app.exception_handler(PublishError)
    async def publish_error(request: Request, _exc: PublishError) -> JSONResponse:
        logger.error(
            "publish failed",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return error_response(500, "enqueue_failed", "Failed to publish message")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return error_response(400, "validation_error", "Invalid request")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = parse_uuid(request.headers.get("x-request-id")) or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except ApiError as exc:
            response = error_response(exc.status_code, exc.code, exc.message, exc.details)
        except StorageError:
            logger.error("dependency unavailable", extra={"request_id": request_id})
            response = error_response(503, "dependency_unavailable", "Dependency unavailable")
        except Exception as exc:
            logger.error(
                "unhandled error %s",
                type(exc).__name__,
                extra={
                    "request_id": request_id,
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
            response = error_response(500, "internal_error", "Internal error")
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "request_id": request_id,
                "user_id": getattr(request.state, "user_id", None),
            },
        )
        return response

    return app


async def _close(resource) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception as exc:
        logger.error("shutdown close failed %s", type(exc).__name__)
