import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from chat.textutil import canonical_uuid


def resolve_request_id(header: str | None) -> str:
    canonical = canonical_uuid(header)
    if canonical is not None:
        return canonical
    return str(uuid.uuid4())


class AuthMiddleware:
    """Require X-Auth-User-Id. X-User-Id is ignored. BLOCKED is 403."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = Headers(scope=scope)
        request_id = resolve_request_id(headers.get("x-request-id"))
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["user_id"] = None

        if path != "/health":
            role = (headers.get("x-auth-role") or "").strip()
            if role == "BLOCKED":
                await _send_error(
                    scope,
                    receive,
                    send,
                    request_id,
                    403,
                    "forbidden",
                    "User is blocked",
                )
                return
            user_id = canonical_uuid(headers.get("x-auth-user-id"))
            if user_id is None:
                await _send_error(
                    scope,
                    receive,
                    send,
                    request_id,
                    401,
                    "unauthenticated",
                    "Missing or invalid X-Auth-User-Id",
                )
                return
            state["user_id"] = user_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers_out = MutableHeaders(scope=message)
                headers_out["X-Request-Id"] = request_id
            await send(message)

        await self.app(scope, receive, send_with_id)


async def _send_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    request_id: str,
    status: int,
    code: str,
    message: str,
) -> None:
    response = JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )
    response.headers["X-Request-Id"] = request_id
    await response(scope, receive, send)


def request_id_of(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


def user_id_of(request: Request) -> str:
    return str(request.state.user_id)
