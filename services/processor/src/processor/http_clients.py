from __future__ import annotations

import base64
import math
import time
from collections.abc import Callable
from typing import Any

import httpx

from processor.errors import PermanentFailure, TransientFailure
from processor.retry import retry_call


class _RetryableHttp(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class _BadResponse(Exception):
    pass


class OcrClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_attempts: int,
        sleeper: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._attempts = max_attempts
        self._sleep = sleeper
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def recognize(self, png: bytes, request_id: str) -> str:
        def once() -> str:
            try:
                response = self._client.post(
                    f"{self._base}/ocr",
                    files={"image": ("page.png", png, "image/png")},
                    headers={"X-Request-Id": request_id},
                )
            except httpx.TimeoutException as exc:
                raise _RetryableHttp(504) from exc
            except httpx.TransportError as exc:
                raise _RetryableHttp(0) from exc
            if response.status_code == 200:
                return _ocr_text(response)
            if 500 <= response.status_code <= 599:
                raise _RetryableHttp(response.status_code)
            raise _BadResponse(f"ocr http {response.status_code}")

        try:
            return retry_call(
                once,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: isinstance(exc, _RetryableHttp),
            )
        except _RetryableHttp as exc:
            raise TransientFailure(
                f"ocr http {exc.status_code}",
                permanent_code="processing_attempts_exceeded",
            ) from exc
        except _BadResponse as exc:
            raise TransientFailure(
                str(exc),
                permanent_code="processing_attempts_exceeded",
            ) from exc


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        max_attempts: int,
        batch_size: int,
        dimension: int,
        model: str,
        sleeper: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._attempts = max_attempts
        self._batch_size = batch_size
        self._dimension = dimension
        self._model = model
        self._sleep = sleeper
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def embed_documents(
        self,
        texts: list[str],
        title: str,
        request_id: str,
    ) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > self._batch_size:
            raise TransientFailure(
                "embedding batch exceeds EMBEDDING_BATCH_SIZE",
                permanent_code="embedding_failed",
            )

        def once() -> list[list[float]]:
            payload = {"texts": texts, "input_type": "document", "title": title}
            try:
                response = self._client.post(
                    f"{self._base}/embed",
                    json=payload,
                    headers={"X-Request-Id": request_id},
                )
            except httpx.TimeoutException as exc:
                raise _RetryableHttp(504) from exc
            except httpx.TransportError as exc:
                raise _RetryableHttp(0) from exc
            if response.status_code == 200:
                return _embeddings(response, expected=len(texts), dimension=self._dimension, model=self._model)
            if 500 <= response.status_code <= 599:
                raise _RetryableHttp(response.status_code)
            raise _BadResponse(f"embedding http {response.status_code}")

        try:
            return retry_call(
                once,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: isinstance(exc, _RetryableHttp),
            )
        except _RetryableHttp as exc:
            raise TransientFailure(
                f"embedding http {exc.status_code}",
                permanent_code="embedding_failed",
            ) from exc
        except _BadResponse as exc:
            raise TransientFailure(str(exc), permanent_code="embedding_failed") from exc

    def embed_image(self, image: bytes, request_id: str) -> list[float]:
        payload = {"images": [base64.standard_b64encode(image).decode("ascii")]}

        def once() -> list[float]:
            try:
                response = self._client.post(
                    f"{self._base}/embed/image",
                    json=payload,
                    headers={"X-Request-Id": request_id},
                )
            except httpx.TimeoutException as exc:
                raise _RetryableHttp(504) from exc
            except httpx.TransportError as exc:
                raise _RetryableHttp(0) from exc
            if response.status_code == 200:
                return _image_embedding(response, dimension=self._dimension, model=self._model)
            if response.status_code == 400:
                raise PermanentFailure("embedding_failed")
            if 500 <= response.status_code <= 599:
                raise _RetryableHttp(response.status_code)
            raise _BadResponse(f"embedding http {response.status_code}")

        try:
            return retry_call(
                once,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: isinstance(exc, _RetryableHttp),
            )
        except _RetryableHttp as exc:
            raise TransientFailure(
                f"embedding http {exc.status_code}",
                permanent_code="embedding_failed",
            ) from exc
        except _BadResponse as exc:
            raise TransientFailure(str(exc), permanent_code="embedding_failed") from exc


def _ocr_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError as exc:
        raise _RetryableHttp(200) from exc
    if not isinstance(body, dict) or not isinstance(body.get("text"), str):
        raise _RetryableHttp(200)
    return body["text"]


def _embeddings(
    response: httpx.Response,
    *,
    expected: int,
    dimension: int,
    model: str,
) -> list[list[float]]:
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise _RetryableHttp(200) from exc
    if not isinstance(body, dict):
        raise _RetryableHttp(200)
    if body.get("model") != model or body.get("dimension") != dimension:
        raise _RetryableHttp(200)
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != expected:
        raise _RetryableHttp(200)
    parsed: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimension:
            raise _RetryableHttp(200)
        numbers: list[float] = []
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                raise _RetryableHttp(200)
            numbers.append(float(item))
        parsed.append(numbers)
    return parsed


def _image_embedding(response: httpx.Response, *, dimension: int, model: str) -> list[float]:
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise _RetryableHttp(200) from exc
    if isinstance(body, dict) and _embedding_is_empty(body.get("embeddings")):
        raise PermanentFailure("embedding_failed")
    return _embeddings(response, expected=1, dimension=dimension, model=model)[0]


def _embedding_is_empty(vectors: Any) -> bool:
    if not isinstance(vectors, list) or len(vectors) == 0:
        return isinstance(vectors, list)
    first = vectors[0]
    return isinstance(first, list) and len(first) == 0
