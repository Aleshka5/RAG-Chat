"""Local ASGI servers for proxy tests. Real file-collector, chat, and frontend are not used."""

import asyncio
from collections.abc import Awaitable, Callable

import uvicorn

Handler = Callable[..., Awaitable[None]]


class Upstream:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.handler: Handler | None = None

    async def __call__(self, scope: dict, receive: Handler, send: Handler) -> None:
        if scope["type"] != "http":
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body") or b"")
            if not message.get("more_body", False):
                break
        headers = [
            (name.decode("latin-1"), value.decode("latin-1")) for name, value in scope["headers"]
        ]
        self.requests.append(
            {
                "method": scope["method"],
                "path": scope["path"],
                "query": scope["query_string"].decode("latin-1"),
                "headers": headers,
                "body": bytes(body),
            }
        )
        if self.handler is not None:
            await self.handler(scope, send, bytes(body))
            return
        payload = b'{"ok":true}'
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-upstream-path", scope["path"].encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


class Running:
    def __init__(self, server: uvicorn.Server, task: asyncio.Task[None], port: int) -> None:
        self.server = server
        self.task = task
        self.port = port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


async def start_server(app: object) -> Running:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            sockets = []
            if server.started and server.servers:
                sockets = list(server.servers[0].sockets or [])
            if sockets:
                port = sockets[0].getsockname()[1]
                return Running(server, task, port)
            await asyncio.sleep(0.01)
        raise RuntimeError("server did not start")
    except Exception:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        raise


async def stop_server(running: Running) -> None:
    running.server.should_exit = True
    await asyncio.wait_for(running.task, timeout=5)
