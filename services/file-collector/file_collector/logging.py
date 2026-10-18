"""JSON logs. Secrets, PDF bytes, and document text are never written."""

import json
import logging
from datetime import UTC, datetime

_FIELDS = ("request_id", "message_id", "file_id", "user_id", "chat_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname.lower(),
            "service": "file-collector",
            "message": record.getMessage(),
        }
        for key in _FIELDS:
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("file_collector").setLevel(level.upper())
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "aio_pika",
        "aiormq",
        "motor",
        "pymongo",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
