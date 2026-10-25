from dataclasses import dataclass
from typing import Protocol

import httpx

from embedding.errors import UpstreamFailed, UpstreamTimeout


@dataclass(frozen=True)
class ImageInput:
    """One image for the embedding model. There is no text and no task prefix."""

    media_type: str
    base64_data: str


class TextEncoder(Protocol):
    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]: ...

    def embed_images(
        self,
        images: list[ImageInput],
        *,
        request_id: str | None = None,
    ) -> list[list[float]]: ...

    def healthy(self) -> bool: ...

    def close(self) -> None: ...


class LlamaEncoder:
    """Call llama-server ``POST /v1/embeddings`` and return vectors in input order."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        client: httpx.Client | None = None,
        process: object | None = None,
        images_ready: bool = True,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._timeout = timeout_seconds
        self._process = process
        self.images_ready = images_ready

    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]:
        return self._embeddings(
            {"input": texts, "encoding_format": "float"},
            len(texts),
            request_id,
        )

    def embed_images(
        self,
        images: list[ImageInput],
        *,
        request_id: str | None = None,
    ) -> list[list[float]]:
        if not self.images_ready:
            raise UpstreamFailed("Embedding upstream failed")
        return self._embeddings(image_embeddings_body(images), len(images), request_id)

    def _embeddings(
        self,
        body: dict[str, object],
        count: int,
        request_id: str | None,
    ) -> list[list[float]]:
        headers = {}
        if request_id:
            headers["X-Request-Id"] = request_id
        try:
            response = self._client.post(
                "/v1/embeddings",
                json=body,
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
            payload = response.json()
        except ValueError as exc:
            raise UpstreamFailed("Embedding upstream failed") from exc
        return _ordered_embeddings(payload, count)

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


def image_embeddings_body(images: list[ImageInput]) -> dict[str, object]:
    """JSON body for llama.cpp b11721 ``POST /v1/embeddings``.

    A multimodal item is an object with a ``content`` array. Putting the
    ``image_url`` part directly in ``input`` is rejected. Image-only content
    has no text part and no task prefix.
    """
    return {
        "input": [
            {
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.media_type};base64,{image.base64_data}",
                        },
                    }
                ]
            }
            for image in images
        ],
        "encoding_format": "float",
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
