"""Environment configuration. Required variables have no defaults."""

import logging
import os

from file_collector.errors import ConfigError

logger = logging.getLogger("file_collector")

_REQUIRED = (
    "MONGODB_URI",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "RABBITMQ_URL",
)
_LEVELS = {"debug", "info", "warning", "error"}


class Settings:
    def __init__(
        self,
        *,
        mongodb_uri: str,
        s3_endpoint: str,
        s3_access_key: str,
        s3_secret_key: str,
        rabbitmq_url: str,
        s3_bucket: str = "documents",
        s3_region: str = "us-east-1",
        rabbitmq_exchange: str = "doc_events",
        rabbitmq_dlx: str = "doc_events_dlq",
        port: int = 8081,
        max_upload_bytes: int = 524288000,
        log_level: str = "info",
        stale_processing_seconds: int = 900,
    ) -> None:
        self.mongodb_uri = mongodb_uri
        self.s3_endpoint = s3_endpoint
        self.s3_access_key = s3_access_key
        self.s3_secret_key = s3_secret_key
        self.rabbitmq_url = rabbitmq_url
        self.s3_bucket = s3_bucket
        self.s3_region = s3_region
        self.rabbitmq_exchange = rabbitmq_exchange
        self.rabbitmq_dlx = rabbitmq_dlx
        self.port = port
        self.max_upload_bytes = max_upload_bytes
        self.log_level = log_level
        self.stale_processing_seconds = stale_processing_seconds

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [name for name in _REQUIRED if not os.environ.get(name)]
        if missing:
            for name in missing:
                logger.error("missing required environment variable %s", name)
            raise ConfigError(missing)

        invalid: list[str] = []
        port = _parse_int("FILE_COLLECTOR_PORT", 8081, invalid)
        max_upload = _parse_int("MAX_UPLOAD_BYTES", 524288000, invalid)
        stale = _parse_int("STALE_PROCESSING_SECONDS", 900, invalid)
        level = _parse_level("LOG_LEVEL", invalid)
        bucket = _optional("S3_BUCKET", "documents")
        region = _optional("S3_REGION", "us-east-1")
        exchange = _optional("RABBITMQ_EXCHANGE", "doc_events")
        dlx = _optional("RABBITMQ_DLX", "doc_events_dlq")

        if port is not None and not 1 <= port <= 65535:
            invalid.append("FILE_COLLECTOR_PORT")
        if max_upload is not None and max_upload < 1:
            invalid.append("MAX_UPLOAD_BYTES")
        if stale is not None and stale < 0:
            invalid.append("STALE_PROCESSING_SECONDS")
        if not bucket:
            invalid.append("S3_BUCKET")
        if not region:
            invalid.append("S3_REGION")
        if not exchange:
            invalid.append("RABBITMQ_EXCHANGE")
        if not dlx:
            invalid.append("RABBITMQ_DLX")

        if invalid or port is None or max_upload is None or stale is None:
            names = list(dict.fromkeys(invalid))
            for name in names:
                logger.error("invalid environment variable %s", name)
            raise ConfigError(names)

        return cls(
            mongodb_uri=os.environ["MONGODB_URI"],
            s3_endpoint=os.environ["S3_ENDPOINT"],
            s3_access_key=os.environ["S3_ACCESS_KEY"],
            s3_secret_key=os.environ["S3_SECRET_KEY"],
            rabbitmq_url=os.environ["RABBITMQ_URL"],
            s3_bucket=bucket,
            s3_region=region,
            rabbitmq_exchange=exchange,
            rabbitmq_dlx=dlx,
            port=port,
            max_upload_bytes=max_upload,
            log_level=level,
            stale_processing_seconds=stale,
        )


def _optional(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _parse_int(name: str, default: int, invalid: list[str]) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        invalid.append(name)
        return None


def _parse_level(name: str, invalid: list[str]) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return "info"
    level = raw.strip().lower()
    if level not in _LEVELS:
        invalid.append(name)
        return "info"
    return level
