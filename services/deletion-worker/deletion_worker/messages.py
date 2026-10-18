import json
import uuid
from datetime import UTC, datetime

from deletion_worker.errors import PermanentMessageError
from deletion_worker.model import DeleteMessage, FileRecord

APP_ID = "deletion-worker"
DELETE_MESSAGE_TYPE = "doc.delete"


def parse_delete_message(raw: bytes | str) -> DeleteMessage:
    try:
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = raw
        body = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermanentMessageError("invalid_json") from exc
    if not isinstance(body, dict):
        raise PermanentMessageError("invalid_json")

    schema_version = body.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise PermanentMessageError("unknown_schema_version")
    if body.get("message_type") != DELETE_MESSAGE_TYPE:
        raise PermanentMessageError("invalid_message_type")

    return DeleteMessage(
        message_id=_canonical_uuid(body.get("message_id")),
        file_id=_canonical_uuid(body.get("file_id"), version=4),
        user_id=_canonical_uuid(body.get("user_id")),
        s3_key=_non_empty_string(body.get("s3_key"), "invalid_s3_key"),
        created_at=_created_at(body.get("created_at")),
    )


def build_delete_payload(
    file: FileRecord,
    message_id: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_type": DELETE_MESSAGE_TYPE,
        "message_id": message_id,
        "file_id": file.file_id,
        "user_id": file.user_id,
        "s3_key": file.s3_key,
        "created_at": format_timestamp(created_at),
    }


def format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_uuid(value: object, version: int | None = None) -> str:
    if not isinstance(value, str):
        raise PermanentMessageError("invalid_uuid")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise PermanentMessageError("invalid_uuid") from exc
    if str(parsed) != value:
        raise PermanentMessageError("invalid_uuid")
    if version is not None and parsed.version != version:
        raise PermanentMessageError("invalid_uuid")
    return value


def _non_empty_string(value: object, reason: str) -> str:
    if not isinstance(value, str) or value == "":
        raise PermanentMessageError(reason)
    return value


def _created_at(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PermanentMessageError("invalid_created_at")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise PermanentMessageError("invalid_created_at") from exc
    return parsed.astimezone(UTC)
