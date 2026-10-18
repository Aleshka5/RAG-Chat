from fastapi.responses import JSONResponse


class ChatError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ValidationFailed(ChatError):
    def __init__(self, fields: list[str]) -> None:
        super().__init__(400, "validation_error", "Invalid request")
        self.fields = fields


class ChatNotFound(ChatError):
    def __init__(self) -> None:
        super().__init__(404, "chat_not_found", "Chat not found")


class DependencyUnavailable(ChatError):
    def __init__(self, message: str = "Dependency unavailable") -> None:
        super().__init__(503, "dependency_unavailable", message)


class UpstreamFailed(ChatError):
    def __init__(self, message: str = "Upstream request failed") -> None:
        super().__init__(502, "upstream_failed", message)


class UpstreamTimeout(ChatError):
    def __init__(self, message: str = "LLM timed out") -> None:
        super().__init__(504, "upstream_timeout", message)


def error_response(exc: ChatError, request_id: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"error": {"code": exc.code, "message": exc.message}}
    fields = getattr(exc, "fields", None)
    if fields:
        body["error"]["details"] = {"fields": list(fields)}
    response = JSONResponse(status_code=exc.status, content=body)
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response
