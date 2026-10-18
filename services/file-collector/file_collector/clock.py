"""UTC timestamps as ISO-8601 with a Z suffix."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        fraction = f"{value.microsecond:06d}".rstrip("0")
        text = f"{text}.{fraction}"
    return f"{text}Z"
