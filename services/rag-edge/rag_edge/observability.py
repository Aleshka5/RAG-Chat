"""JSON logs. Document text, PDF bytes, prompts, and secret values are never written."""

import json
import logging

LOG_FIELDS = ("request_id", "message_id", "file_id", "user_id", "chat_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "service": "rag-edge",
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for key in LOG_FIELDS:
            value = record.__dict__.get(key)
            if value:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    log = logging.getLogger("rag-edge")
    log.handlers.clear()
    log.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(level.upper())
