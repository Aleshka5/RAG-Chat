from rag_common.errors import DEFAULT_MESSAGE, STATUS_BY_CODE, ErrorCode, error_envelope, http_error


def test_envelope_omits_details_until_set() -> None:
    body = error_envelope(ErrorCode.FILE_NOT_FOUND)
    assert body == {"error": {"code": "file_not_found", "message": "File not found"}}
    assert "details" not in body["error"]


def test_envelope_keeps_empty_details_when_passed() -> None:
    body = error_envelope("file_not_found", details={})
    assert body["error"]["details"] == {}


def test_openapi_examples() -> None:
    status, body = http_error(ErrorCode.UNAUTHENTICATED)
    assert status == 401
    assert body["error"]["message"] == "Missing or invalid X-Auth-User-Id"

    status, body = http_error(ErrorCode.FORBIDDEN)
    assert status == 403
    assert body["error"] == {"code": "forbidden", "message": "User is blocked"}

    status, body = http_error(
        ErrorCode.DUPLICATE_FILE,
        details={"file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"},
    )
    assert status == 409
    assert body["error"]["details"]["file_id"] == "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    assert body["error"]["message"] == "A file with the same content already exists"

    status, body = http_error(ErrorCode.VALIDATION_ERROR, details={"fields": ["content"]})
    assert status == 400
    assert body["error"]["details"] == {"fields": ["content"]}

    status, body = http_error(ErrorCode.UPSTREAM_TIMEOUT)
    assert status == 504
    assert body["error"]["message"] == "LLM timed out"


def test_status_table_matches_api() -> None:
    assert STATUS_BY_CODE[ErrorCode.FILE_TOO_LARGE] == 413
    assert STATUS_BY_CODE[ErrorCode.UNSUPPORTED_MEDIA_TYPE] == 415
    assert STATUS_BY_CODE[ErrorCode.FILE_BUSY] == 409
    assert STATUS_BY_CODE[ErrorCode.ENQUEUE_FAILED] == 500
    assert STATUS_BY_CODE[ErrorCode.UPSTREAM_FAILED] == 502
    assert STATUS_BY_CODE[ErrorCode.DEPENDENCY_UNAVAILABLE] == 503
    assert STATUS_BY_CODE[ErrorCode.CHAT_NOT_FOUND] == 404
    assert set(STATUS_BY_CODE) == set(DEFAULT_MESSAGE)


def test_unknown_code_is_rejected() -> None:
    try:
        http_error("unauthorized")
    except KeyError:
        return
    raise AssertionError("gateway string error must not be a RAG code")
