"""``doc.process`` and ``doc.delete`` bodies from docs/messaging.md.

``x-death`` is not a body field. ``schema_version`` is the integer ``1``.
``created_at`` is UTC ISO-8601 with a ``Z`` suffix.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
)

PROCESS_MESSAGE_TYPE = "doc.process"
DELETE_MESSAGE_TYPE = "doc.delete"


def parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("created_at must be ISO-8601 UTC") from exc
    else:
        raise ValueError("created_at must be ISO-8601 UTC")
    if parsed.tzinfo is None:
        raise ValueError("created_at must be UTC")
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    utc = value.astimezone(UTC)
    if utc.microsecond:
        fraction = f"{utc.microsecond:06d}".rstrip("0")
        return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction}Z"
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _schema_version(value: Any) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("schema_version must be integer 1")
    return value


class _WireMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("message_id", "file_id", "user_id", check_fields=False)
    def _dump_uuid(self, value: UUID) -> str:
        return str(value)

    @field_serializer("created_at", check_fields=False)
    def _dump_created_at(self, value: datetime) -> str:
        return format_utc(value)


class DocProcess(_WireMessage):
    schema_version: int
    message_type: str
    message_id: UUID
    file_id: UUID
    user_id: UUID
    s3_key: str = Field(min_length=1)
    file_name: str
    content_type: str
    created_at: datetime

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: Any) -> int:
        return _schema_version(value)

    @field_validator("message_type")
    @classmethod
    def _message_type(cls, value: str) -> str:
        if value != PROCESS_MESSAGE_TYPE:
            raise ValueError("message_type must be doc.process")
        return value

    @field_validator("content_type")
    @classmethod
    def _content_type(cls, value: str) -> str:
        if value != "application/pdf":
            raise ValueError("content_type must be application/pdf")
        return value

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at(cls, value: Any) -> datetime:
        return parse_utc(value)


class DocDelete(_WireMessage):
    schema_version: int
    message_type: str
    message_id: UUID
    file_id: UUID
    user_id: UUID
    s3_key: str = Field(min_length=1)
    created_at: datetime

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_schema_version(cls, value: Any) -> int:
        return _schema_version(value)

    @field_validator("message_type")
    @classmethod
    def _message_type(cls, value: str) -> str:
        if value != DELETE_MESSAGE_TYPE:
            raise ValueError("message_type must be doc.delete")
        return value

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at(cls, value: Any) -> datetime:
        return parse_utc(value)


def parse_message(data: dict[str, Any]) -> DocProcess | DocDelete:
    """Parse one queue body. Unknown ``message_type`` or schema is a validation error."""
    message_type = data.get("message_type") if isinstance(data, dict) else None
    if message_type == PROCESS_MESSAGE_TYPE:
        return DocProcess.model_validate(data)
    if message_type == DELETE_MESSAGE_TYPE:
        return DocDelete.model_validate(data)
    raise ValidationError.from_exception_data(
        "message",
        [
            {
                "type": "value_error",
                "loc": ("message_type",),
                "input": message_type,
                "ctx": {"error": ValueError("message_type must be doc.process or doc.delete")},
            }
        ],
    )
