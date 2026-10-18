import json
import logging

from rag_common.logging import LOG_FIELD_NAMES, JsonFormatter, fields_from_mapping, log_extra


def test_log_record_keeps_known_fields_only() -> None:
    extra = log_extra(service="chat", request_id="abc", file_id="file-1")
    assert extra == {"service": "chat", "request_id": "abc", "file_id": "file-1"}
    assert set(LOG_FIELD_NAMES) == {
        "service",
        "request_id",
        "message_id",
        "file_id",
        "user_id",
        "chat_id",
    }

    record = logging.LogRecord(
        name="chat",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="indexed",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    record.text = "секретный текст документа"
    record.prompt = "контекст"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["level"] == "info"
    assert payload["message"] == "indexed"
    assert payload["service"] == "chat"
    assert payload["request_id"] == "abc"
    assert "message_id" not in payload
    assert "user_id" not in payload
    assert "chat_id" not in payload
    assert "text" not in payload
    assert "prompt" not in payload
    assert "секретный" not in JsonFormatter().format(record)


def test_mapping_filter_drops_nulls_and_secrets() -> None:
    copied = fields_from_mapping(
        {
            "service": "processor",
            "user_id": None,
            "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
            "S3_SECRET_KEY": "super-secret",
            "text": "page text",
        }
    )
    assert copied == {
        "service": "processor",
        "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
    }
