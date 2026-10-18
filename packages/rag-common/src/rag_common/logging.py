"""JSON log fields from docs/architecture.md.

Each record includes ``service``, ``request_id``, ``message_id``, ``file_id``,
``user_id``, and ``chat_id`` when those values are known. Document text, PDF
bytes, the prompt with context, and secrets are not fields of this record.
"""

import json
import logging
from collections.abc import Mapping
from typing import Any

LOG_FIELD_NAMES = ("service", "request_id", "message_id", "file_id", "user_id", "chat_id")


def log_extra(
    *,
    service: str,
    request_id: str | None = None,
    message_id: str | None = None,
    file_id: str | None = None,
    user_id: str | None = None,
    chat_id: str | None = None,
) -> dict[str, str]:
    """``extra`` dict for ``logging``: only the known structured fields."""
    fields = {
        "service": service,
        "request_id": request_id,
        "message_id": message_id,
        "file_id": file_id,
        "user_id": user_id,
        "chat_id": chat_id,
    }
    return {key: value for key, value in fields.items() if value is not None}


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Unknown structured fields are left out."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for name in LOG_FIELD_NAMES:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps(payload, ensure_ascii=False)


def fields_from_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only the documented field names that are present and not null."""
    return {name: values[name] for name in LOG_FIELD_NAMES if values.get(name) is not None}
