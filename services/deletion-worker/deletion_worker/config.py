import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("deletion_worker")

_REQUIRED = (
    "MONGODB_URI",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "QDRANT_URL",
    "RABBITMQ_URL",
)

_LOG_LEVELS = {"debug", "info", "warning", "error"}


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str
    qdrant_url: str
    qdrant_collection: str
    rabbitmq_url: str
    rabbitmq_exchange: str
    rabbitmq_dlx: str
    log_level: str
    deletion_concurrency: int
    stale_processing_seconds: int
    sweep_interval_seconds: int
    delete_requeue_after_seconds: int


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    missing = [name for name in _REQUIRED if not env.get(name, "").strip()]
    if missing:
        for name in missing:
            logger.error("missing required environment variable: %s", name)
        raise SystemExit(1)

    log_level = env.get("LOG_LEVEL", "info").strip().lower()
    if log_level not in _LOG_LEVELS:
        logger.error("invalid environment variable: LOG_LEVEL")
        raise SystemExit(1)

    return Settings(
        mongodb_uri=env["MONGODB_URI"],
        s3_endpoint=env["S3_ENDPOINT"],
        s3_access_key=env["S3_ACCESS_KEY"],
        s3_secret_key=env["S3_SECRET_KEY"],
        s3_bucket=env.get("S3_BUCKET", "documents").strip() or "documents",
        s3_region=env.get("S3_REGION", "us-east-1").strip() or "us-east-1",
        qdrant_url=env["QDRANT_URL"],
        qdrant_collection=env.get("QDRANT_COLLECTION", "documents").strip() or "documents",
        rabbitmq_url=env["RABBITMQ_URL"],
        rabbitmq_exchange=env.get("RABBITMQ_EXCHANGE", "doc_events").strip() or "doc_events",
        rabbitmq_dlx=env.get("RABBITMQ_DLX", "doc_events_dlq").strip() or "doc_events_dlq",
        log_level=log_level,
        deletion_concurrency=_positive_int(env, "DELETION_CONCURRENCY", 1),
        stale_processing_seconds=_positive_int(env, "STALE_PROCESSING_SECONDS", 900),
        sweep_interval_seconds=_positive_int(env, "SWEEP_INTERVAL_SECONDS", 60),
        delete_requeue_after_seconds=_positive_int(env, "DELETE_REQUEUE_AFTER_SECONDS", 120),
    )


def _positive_int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.error("invalid environment variable: %s", name)
        raise SystemExit(1) from None
    if value < 1:
        logger.error("invalid environment variable: %s", name)
        raise SystemExit(1)
    return value
