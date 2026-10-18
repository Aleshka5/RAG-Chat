import json

import httpx


def openai_sse(tokens: list[str]) -> bytes:
    lines = [
        'data: {"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"index":0,"delta":{"content":""},"finish_reason":null}]}',
        "",
    ]
    for token in tokens:
        payload = json.dumps(
            {"choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]},
            ensure_ascii=False,
        )
        lines.append(f"data: {payload}")
        lines.append("")
    lines.append('data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}')
    lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return ("\n".join(lines)).encode()


class ScriptedTransport(httpx.AsyncBaseTransport):
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.embed_requests: list[httpx.Request] = []
        self.llm_requests: list[httpx.Request] = []
        self.embed_script: list[object] = []
        self.llm_script: list[object] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/embed"):
            self.embed_requests.append(request)
            return self._next(self.embed_script, self._default_embed)
        if path.endswith("/chat/completions"):
            self.llm_requests.append(request)
            return self._next(self.llm_script, self._default_llm)
        return httpx.Response(404, json={"error": "not found"})

    def _next(self, script: list[object], default):
        if not script:
            return default()
        action = script.pop(0)
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            return action()
        return action

    def _default_embed(self) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "embeddings": [[0.01] * self.dim],
                "model": "google/embeddinggemma-2",
                "dimension": self.dim,
            },
        )

    def _default_llm(self) -> httpx.Response:
        return httpx.Response(200, content=openai_sse(["Срок", " годности"]))

    def embed_body(self, index: int = 0) -> dict:
        return json.loads(self.embed_requests[index].content.decode())

    def llm_body(self, index: int = 0) -> dict:
        return json.loads(self.llm_requests[index].content.decode())
