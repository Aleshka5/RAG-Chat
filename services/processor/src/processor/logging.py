from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

SERVICE = "processor"

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
message_id_var: ContextVar[str | None] = ContextVar("message_id", default=None)
file_id_var: ContextVar[str | None] = ContextVar("file_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_CONTEXT = {
    "request_id": request_id_var,
    "message_id": message_id_var,
    "file_id": file_id_var,
    "user_id": user_id_var,
}

_STANDARD_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "service": SERVICE,
            "message": record.getMessage(),
        }
        for key, var in _CONTEXT.items():
            value = getattr(record, key, None)
            if value is None:
                value = var.get()
            if value is not None:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS or key in payload or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(SERVICE)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def get_logger() -> logging.Logger:
    return logging.getLogger(SERVICE)
