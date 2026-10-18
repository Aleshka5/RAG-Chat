import json
import time
from collections.abc import AsyncIterator

import httpx

from chat.config import Settings
from chat.errors import UpstreamFailed, UpstreamTimeout


class _Retryable(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _Fatal(Exception):
    pass


class LLMClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(settings.llm_timeout_seconds),
        )

    def stream(self, messages: list[dict[str, str]], request_id: str) -> AsyncIterator[str]:
        return self._stream(messages, request_id)

    async def _stream(self, messages: list[dict[str, str]], request_id: str) -> AsyncIterator[str]:
        last: _Retryable | None = None
        for attempt in range(2):
            yielded = False
            try:
                async for token in self._attempt(messages, request_id):
                    yielded = True
                    yield token
                return
            except _Retryable as exc:
                last = exc
                if yielded or attempt == 1:
                    self._raise_final(exc)
            except _Fatal as exc:
                raise UpstreamFailed() from exc
        if last is not None:
            self._raise_final(last)
        raise UpstreamFailed()

    async def _attempt(self, messages: list[dict[str, str]], request_id: str) -> AsyncIterator[str]:
        payload = {
            "model": self._settings.llm_model,
            "temperature": self._settings.llm_temperature,
            "stream": True,
            "messages": messages,
        }
        request = self._client.build_request(
            "POST",
            f"{self._settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._settings.llm_api_key}",
                "X-Request-Id": request_id,
            },
            json=payload,
        )
        started = time.monotonic()
        response: httpx.Response | None = None
        try:
            try:
                response = await self._client.send(request, stream=True)
            except httpx.TimeoutException as exc:
                raise _Retryable("timeout") from exc
            except httpx.TransportError as exc:
                raise _Retryable("network") from exc
            if response.status_code != 200:
                await response.aread()
                status = response.status_code
                if status == 429 or status >= 500:
                    raise _Retryable("status")
                raise _Fatal()
            async for line in response.aiter_lines():
                if time.monotonic() - started > self._settings.llm_timeout_seconds:
                    raise _Retryable("timeout")
                kind, token = _parse_line(line)
                if kind == "skip":
                    continue
                if kind == "done":
                    return
                if kind == "stop":
                    if token:
                        yield token
                    return
                if token:
                    yield token
            raise _Retryable("network")
        finally:
            if response is not None:
                await response.aclose()

    @staticmethod
    def _raise_final(exc: _Retryable) -> None:
        if exc.kind == "timeout":
            raise UpstreamTimeout() from exc
        raise UpstreamFailed() from exc

    async def close(self) -> None:
        await self._client.aclose()


def _parse_line(line: str) -> tuple[str, str | None]:
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return "skip", None
    if not stripped.startswith("data:"):
        return "skip", None
    data = stripped[5:].strip()
    if data == "[DONE]":
        return "done", None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise _Fatal() from exc
    if not isinstance(payload, dict):
        raise _Fatal()
    choices = payload.get("choices")
    if payload.get("error") and not choices:
        raise _Fatal()
    if not isinstance(choices, list) or not choices:
        return "skip", None
    choice = choices[0]
    if not isinstance(choice, dict):
        raise _Fatal()
    delta = choice.get("delta") or {}
    if not isinstance(delta, dict):
        delta = {}
    content = delta.get("content")
    token = content if isinstance(content, str) and content != "" else None
    finish = choice.get("finish_reason")
    if finish not in (None, "stop"):
        raise _Fatal()
    if finish == "stop":
        return "stop", token
    if token is None:
        return "skip", None
    return "token", token
