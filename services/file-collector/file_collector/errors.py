"""API and infrastructure errors."""

from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class ConfigError(Exception):
    def __init__(self, variables: list[str]) -> None:
        self.variables = variables
        super().__init__("invalid configuration: " + ", ".join(variables))


class DuplicateActiveFile(Exception):
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id
        super().__init__(file_id)


class StorageError(Exception):
    pass


class ObjectNotFound(Exception):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


class PublishError(Exception):
    pass


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details),
    )
