import base64
from typing import Protocol

import httpx

from embedding.constants import DEFAULT_MEDIA_MARKER
from embedding.errors import UpstreamFailed, UpstreamTimeout


class Encoder(Protocol):
    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]: ...

    def embed_images(
        self, images: list[bytes], *, request_id: str | None = None
    ) -> list[list[float]]: ...

    def healthy(self) -> bool: ...

    def close(self) -> None: ...


class LlamaEncoder:
    """Call llama-server ``POST /v1/embeddings`` and return vectors in input order.

    Text and images share the endpoint and the model. An image input is an
    object holding the media marker and the base64 bytes; llama.cpp replaces
    the marker with the image tokens, and the pooled vector lands in the same
    space as text. Images carry no task prefix: the model card passes them
    bare.

    The marker is not a constant. Current builds mint a per-process nonce and
    publish it as ``media_marker`` in ``GET /props``, so it is read from the
    server once and cached; a 500 from a marker mismatch would otherwise look
    exactly like a broken image.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        client: httpx.Client | None = None,
        process: object | None = None,
        media_marker: str | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._timeout = timeout_seconds
        self._process = process
        self._media_marker = media_marker

    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]:
        return self._request(
            {"input": list(texts), "encoding_format": "float"},
            len(texts),
            request_id,
        )

    def embed_images(
        self, images: list[bytes], *, request_id: str | None = None
    ) -> list[list[float]]:
        marker = self.media_marker()
        return self._request(
            {
                "input": [_image_input(image, marker) for image in images],
                "encoding_format": "float",
            },
            len(images),
            request_id,
        )

    def media_marker(self) -> str:
        if self._media_marker is None:
            self._media_marker = self._fetch_media_marker()
        return self._media_marker

    def healthy(self) -> bool:
        try:
            response = self._client.get("/health", timeout=2.0)
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        return isinstance(body, dict) and body.get("status") == "ok"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        process = self._process
        if process is None:
            return
        poll = getattr(process, "poll", None)
        if poll is None or poll() is not None:
            return
        terminate = getattr(process, "terminate", None)
        if terminate is not None:
            terminate()
        wait = getattr(process, "wait", None)
        if wait is None:
            return
        try:
            wait(timeout=10)
        except Exception:
            kill = getattr(process, "kill", None)
            if kill is not None:
                kill()

    def _fetch_media_marker(self) -> str:
        try:
            response = self._client.get("/props", timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("Embedding timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamFailed("Embedding upstream failed") from exc
        if response.status_code != 200:
            raise UpstreamFailed("Embedding upstream failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise UpstreamFailed("Embedding upstream failed") from exc
        marker = body.get("media_marker") if isinstance(body, dict) else None
        if not isinstance(marker, str) or marker == "":
            return DEFAULT_MEDIA_MARKER
        return marker

    def _request(
        self,
        payload: dict[str, object],
        count: int,
        request_id: str | None,
    ) -> list[list[float]]:
        headers = {}
        if request_id:
            headers["X-Request-Id"] = request_id
        try:
            response = self._client.post(
                "/v1/embeddings",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("Embedding timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamFailed("Embedding upstream failed") from exc
        if response.status_code != 200:
            raise UpstreamFailed("Embedding upstream failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise UpstreamFailed("Embedding upstream failed") from exc
        return _ordered_embeddings(body, count)


def _image_input(image: bytes, marker: str) -> dict[str, object]:
    """One image as llama-server's multimodal input: marker plus base64 bytes."""
    return {
        "prompt_string": marker,
        "multimodal_data": [base64.b64encode(image).decode("ascii")],
    }


def _ordered_embeddings(payload: object, count: int) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise UpstreamFailed("Embedding upstream failed")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != count:
        raise UpstreamFailed("Embedding upstream failed")
    ordered: list[list[float] | None] = [None] * count
    for item in data:
        if not isinstance(item, dict):
            raise UpstreamFailed("Embedding upstream failed")
        index = item.get("index")
        embedding = item.get("embedding")
        if isinstance(index, bool) or not isinstance(index, int):
            raise UpstreamFailed("Embedding upstream failed")
        if index < 0 or index >= count or ordered[index] is not None:
            raise UpstreamFailed("Embedding upstream failed")
        if not isinstance(embedding, list):
            raise UpstreamFailed("Embedding upstream failed")
        ordered[index] = embedding
    if any(vector is None for vector in ordered):
        raise UpstreamFailed("Embedding upstream failed")
    return [vector for vector in ordered if vector is not None]
