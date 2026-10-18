from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def format_z(value: datetime) -> str:
    moment = value.astimezone(UTC).replace(microsecond=0)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
