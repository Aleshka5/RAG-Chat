"""RAG error envelope from docs/api.md and docs/openapi.yaml.

``details`` is omitted unless the caller supplies it. Messages below are the
English phrases from the OpenAPI examples. ``enqueue_failed`` and
``upstream_failed`` have no example phrase in the schema; the strings here are
the short developer messages for those codes.

The Auth Gateway body ``{"error": "unauthorized"}`` is not this envelope.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    FILE_NOT_FOUND = "file_not_found"
    CHAT_NOT_FOUND = "chat_not_found"
    DUPLICATE_FILE = "duplicate_file"
    FILE_BUSY = "file_busy"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    ENQUEUE_FAILED = "enqueue_failed"
    UPSTREAM_FAILED = "upstream_failed"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"


STATUS_BY_CODE: dict[str, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.CHAT_NOT_FOUND: 404,
    ErrorCode.DUPLICATE_FILE: 409,
    ErrorCode.FILE_BUSY: 409,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: 415,
    ErrorCode.ENQUEUE_FAILED: 500,
    ErrorCode.UPSTREAM_FAILED: 502,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
}

DEFAULT_MESSAGE: dict[str, str] = {
    ErrorCode.VALIDATION_ERROR: "Invalid request",
    ErrorCode.UNAUTHENTICATED: "Missing or invalid X-Auth-User-Id",
    ErrorCode.FORBIDDEN: "User is blocked",
    ErrorCode.FILE_NOT_FOUND: "File not found",
    ErrorCode.CHAT_NOT_FOUND: "Chat not found",
    ErrorCode.DUPLICATE_FILE: "A file with the same content already exists",
    ErrorCode.FILE_BUSY: "File cannot be deleted in its current state",
    ErrorCode.FILE_TOO_LARGE: "File exceeds the size limit",
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: "Only PDF is accepted",
    ErrorCode.ENQUEUE_FAILED: "Queue publish was not confirmed",
    ErrorCode.UPSTREAM_FAILED: "Upstream request failed",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "Dependency unavailable",
    ErrorCode.UPSTREAM_TIMEOUT: "LLM timed out",
}


def error_envelope(
    code: ErrorCode | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the JSON object ``{"error": {"code", "message", ...}}``."""
    key = str(code)
    if key not in DEFAULT_MESSAGE:
        raise KeyError(key)
    body: dict[str, Any] = {
        "code": key,
        "message": DEFAULT_MESSAGE[key] if message is None else message,
    }
    if details is not None:
        body["details"] = details
    return {"error": body}


def http_error(
    code: ErrorCode | str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return ``(http_status, envelope)`` for a documented RAG error code."""
    key = str(code)
    if key not in STATUS_BY_CODE:
        raise KeyError(key)
    return STATUS_BY_CODE[key], error_envelope(key, message, details)
