from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from processor.errors import InvalidMessage

MESSAGE_TYPE_PROCESS = "doc.process"
PDF_CONTENT_TYPE = "application/pdf"
IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)
ACCEPTED_CONTENT_TYPES = frozenset({PDF_CONTENT_TYPE, *IMAGE_CONTENT_TYPES})


@dataclass(frozen=True)
class ProcessMessage:
    message_id: str
    file_id: str
    user_id: str
    s3_key: str
    file_name: str
    content_type: str
    created_at: str


def parse_process_message(body: bytes) -> ProcessMessage:
    try:
        text = body.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidMessage("bad_json") from exc
    if not isinstance(data, dict):
        raise InvalidMessage("not_object")
    schema = data.get("schema_version")
    if isinstance(schema, bool) or schema != 1:
        raise InvalidMessage("schema_version")
    if data.get("message_type") != MESSAGE_TYPE_PROCESS:
        raise InvalidMessage("message_type")
    file_name = data.get("file_name")
    if not isinstance(file_name, str):
        raise InvalidMessage("file_name")
    s3_key = data.get("s3_key")
    if not isinstance(s3_key, str) or s3_key == "":
        raise InvalidMessage("s3_key")
    content_type = data.get("content_type")
    if not isinstance(content_type, str) or content_type not in ACCEPTED_CONTENT_TYPES:
        raise InvalidMessage("content_type")
    return ProcessMessage(
        message_id=_uuid(data.get("message_id"), version=4),
        file_id=_uuid(data.get("file_id"), version=4),
        user_id=_uuid(data.get("user_id"), version=None),
        s3_key=s3_key,
        file_name=file_name,
        content_type=content_type,
        created_at=_created_at(data.get("created_at")),
    )


def build_process_message(file_doc: dict[str, Any], message_id: str, created_at: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": MESSAGE_TYPE_PROCESS,
        "message_id": message_id,
        "file_id": file_doc["file_id"],
        "user_id": file_doc["user_id"],
        "s3_key": file_doc["s3_key"],
        "file_name": file_doc["file_name"],
        "content_type": file_doc.get("content_type") or "application/pdf",
        "created_at": created_at,
    }


def _uuid(value: object, *, version: int | None) -> str:
    if not isinstance(value, str):
        raise InvalidMessage("uuid")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise InvalidMessage("uuid") from exc
    if str(parsed) != value:
        raise InvalidMessage("uuid")
    if version is not None and parsed.version != version:
        raise InvalidMessage("uuid")
    return value


def _created_at(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InvalidMessage("created_at")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidMessage("created_at") from exc
    return value
