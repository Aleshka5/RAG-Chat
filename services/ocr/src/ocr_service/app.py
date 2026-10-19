"""HTTP API for POST /ocr and GET /health."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from PIL import Image
from starlette.datastructures import UploadFile

from ocr_service.config import Settings
from ocr_service.engine import OcrEngine
from ocr_service.images import decode_raster

logger = logging.getLogger("ocr")


def create_app(
    engine: OcrEngine,
    settings: Settings | None = None,
    executor: ThreadPoolExecutor | None = None,
) -> FastAPI:
    """Build the service around an already constructed engine.

    Production startup constructs `PaddleMultilingualEngine` on `executor`
    before this function runs, then passes that same pool in. Paddle's
    predictor is used only from the thread that created it. Tests pass a
    fake engine so model weights are not downloaded.
    """
    resolved = settings or Settings()
    if executor is None:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ready = True
        try:
            yield
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title="OCR",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.settings = resolved
    app.state.executor = executor
    app.state.ready = False

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request failed request_id=%s", request_id)
            response = _error(500, "internal_error", "OCR failed")
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "%s %s %s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return _error(400, "validation_error", "Invalid request", fields=["image"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ocr")
    async def ocr(request: Request):
        image, error = await _read_image(request)
        if error is not None:
            return error
        assert image is not None
        try:
            payload = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    executor,
                    _recognize,
                    engine,
                    image,
                ),
                timeout=resolved.ocr_timeout,
            )
        except TimeoutError:
            return _error(504, "upstream_timeout", "OCR timed out")
        except Exception:
            logger.exception("OCR engine failed request_id=%s", request.state.request_id)
            return _error(500, "internal_error", "OCR failed")
        return JSONResponse(status_code=200, content=payload)

    return app


def _recognize(engine: OcrEngine, image: Image.Image) -> dict[str, object]:
    started = time.perf_counter()
    text, confidence = engine.recognize(image)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if not isinstance(text, str):
        text = str(text)
    return {
        "text": text,
        "confidence": _confidence(confidence),
        "processing_time_ms": max(0, elapsed_ms),
    }


def _confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


async def _read_image(request: Request) -> tuple[Image.Image | None, JSONResponse | None]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        return None, _error(
            400,
            "validation_error",
            "Request must be multipart/form-data",
            fields=["image"],
        )
    try:
        form = await request.form()
    except Exception:
        return None, _error(400, "validation_error", "Invalid request", fields=["image"])
    if "image" not in form:
        return None, _error(400, "validation_error", "Image is required", fields=["image"])
    uploaded = form["image"]
    if isinstance(uploaded, str) or not isinstance(uploaded, UploadFile):
        return None, _error(400, "validation_error", "Image is required", fields=["image"])
    data = await uploaded.read()
    if not data:
        return None, _error(400, "validation_error", "Image is empty", fields=["image"])
    image = decode_raster(data)
    if image is None:
        return None, _error(
            400,
            "validation_error",
            "Image could not be decoded",
            fields=["image"],
        )
    return image, None


def _request_id(raw: str | None) -> str:
    if raw is not None and raw.strip() != "":
        try:
            return str(uuid.UUID(raw.strip()))
        except ValueError:
            pass
    return str(uuid.uuid4())


def _error(
    status: int,
    code: str,
    message: str,
    fields: list[str] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message}
    if fields is not None:
        body["details"] = {"fields": fields}
    return JSONResponse(status_code=status, content={"error": body})
