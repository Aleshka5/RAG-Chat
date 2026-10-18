import logging
import math

import httpx

from chat.config import Settings
from chat.errors import DependencyUnavailable, UpstreamFailed
from chat.textutil import truncate_query

logger = logging.getLogger("chat")


class _Retryable(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _TooLong(Exception):
    pass


class EmbeddingClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(settings.embedding_timeout),
        )

    async def embed_query(self, text: str, request_id: str) -> list[float]:
        current = truncate_query(text, self._settings.embedding_max_tokens)
        if len(current) != len(text):
            logger.debug(
                "truncated query for embedding from %s to %s characters",
                len(text),
                len(current),
                extra={"request_id": request_id},
            )
        for _shrink in range(8):
            try:
                return await self._post_with_retry(current, request_id)
            except _TooLong:
                if len(current) <= 1:
                    raise UpstreamFailed() from None
                current = current[: max(1, len(current) // 2)]
        raise UpstreamFailed()

    async def _post_with_retry(self, text: str, request_id: str) -> list[float]:
        last: _Retryable | None = None
        for attempt in range(2):
            try:
                return await self._post_once(text, request_id)
            except _Retryable as exc:
                last = exc
                if attempt == 1:
                    break
        assert last is not None
        if last.kind == "status":
            raise UpstreamFailed() from last
        raise DependencyUnavailable() from last

    async def _post_once(self, text: str, request_id: str) -> list[float]:
        url = f"{self._settings.embedding_url}/embed"
        try:
            response = await self._client.post(
                url,
                headers={"X-Request-Id": request_id},
                json={"texts": [text], "input_type": "query"},
            )
        except httpx.TimeoutException as exc:
            raise _Retryable("timeout") from exc
        except httpx.TransportError as exc:
            raise _Retryable("network") from exc
        if response.status_code == 400:
            if len(text) > 8:
                raise _TooLong()
            raise UpstreamFailed()
        if response.status_code == 429 or response.status_code >= 500:
            raise _Retryable("status")
        if response.status_code != 200:
            raise UpstreamFailed()
        return self._vector(response)

    def _vector(self, response: httpx.Response) -> list[float]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamFailed() from exc
        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise UpstreamFailed()
        vector = embeddings[0]
        if not isinstance(vector, list) or len(vector) != self._settings.embedding_dim:
            raise UpstreamFailed()
        values: list[float] = []
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, int | float):
                raise UpstreamFailed()
            number = float(item)
            if not math.isfinite(number):
                raise UpstreamFailed()
            values.append(number)
        return values

    async def close(self) -> None:
        await self._client.aclose()
