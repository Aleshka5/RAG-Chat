from __future__ import annotations

import os
from dataclasses import dataclass

from processor.errors import ConfigError
from processor.logging import get_logger

REQUIRED = (
    "MONGODB_URI",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "QDRANT_URL",
    "RABBITMQ_URL",
    "EMBEDDING_URL",
    "OCR_URL",
)

LOG_LEVELS = frozenset({"debug", "info", "warning", "error"})
LOCAL_ATTENTION_WINDOW = 1024


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    qdrant_url: str
    rabbitmq_url: str
    embedding_url: str
    ocr_url: str
    s3_bucket: str = "storage"
    s3_region: str = "us-east-1"
    qdrant_collection: str = "documents"
    qdrant_images_collection: str = "images"
    rabbitmq_exchange: str = "doc_events"
    rabbitmq_dlx: str = "doc_events_dlq"
    log_level: str = "info"
    processor_concurrency: int = 1
    chunk_tokens: int = 512
    chunk_overlap_tokens: int = 51
    max_process_attempts: int = 8
    min_extracted_chars: int = 50
    ocr_render_dpi: int = 300
    ocr_timeout: float = 120
    ocr_max_attempts: int = 3
    embedding_timeout: float = 30
    embedding_batch_size: int = 16
    embedding_dim: int = 768
    embedding_max_tokens: int = 1024
    embedding_model: str = "google/embeddinggemma-2"
    qdrant_upsert_batch: int = 64
    stale_processing_seconds: int = 900
    sweep_interval_seconds: int = 60
    upload_requeue_after_seconds: int = 120


def load_settings(environ: os._Environ[str] | dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        logger = get_logger()
        for name in missing:
            logger.error("missing required environment variable %s", name)
        raise SystemExit(1)
    try:
        settings = Settings(
            mongodb_uri=env["MONGODB_URI"],
            s3_endpoint=env["S3_ENDPOINT"].rstrip("/"),
            s3_access_key=env["S3_ACCESS_KEY"],
            s3_secret_key=env["S3_SECRET_KEY"],
            qdrant_url=env["QDRANT_URL"].rstrip("/"),
            rabbitmq_url=env["RABBITMQ_URL"],
            embedding_url=env["EMBEDDING_URL"].rstrip("/"),
            ocr_url=env["OCR_URL"].rstrip("/"),
            s3_bucket=_str(env, "S3_BUCKET", "storage"),
            s3_region=_str(env, "S3_REGION", "us-east-1"),
            qdrant_collection=_str(env, "QDRANT_COLLECTION", "documents"),
            qdrant_images_collection=_str(env, "QDRANT_IMAGES_COLLECTION", "images"),
            rabbitmq_exchange=_str(env, "RABBITMQ_EXCHANGE", "doc_events"),
            rabbitmq_dlx=_str(env, "RABBITMQ_DLX", "doc_events_dlq"),
            log_level=_log_level(env),
            processor_concurrency=_int(env, "PROCESSOR_CONCURRENCY", 1),
            chunk_tokens=_int(env, "CHUNK_TOKENS", 512),
            chunk_overlap_tokens=_int(env, "CHUNK_OVERLAP_TOKENS", 51),
            max_process_attempts=_int(env, "MAX_PROCESS_ATTEMPTS", 8),
            min_extracted_chars=_int(env, "MIN_EXTRACTED_CHARS", 50),
            ocr_render_dpi=_int(env, "OCR_RENDER_DPI", 300),
            ocr_timeout=_float(env, "OCR_TIMEOUT", 120),
            ocr_max_attempts=_int(env, "OCR_MAX_ATTEMPTS", 3),
            embedding_timeout=_float(env, "EMBEDDING_TIMEOUT", 30),
            embedding_batch_size=_int(env, "EMBEDDING_BATCH_SIZE", 16),
            embedding_dim=_int(env, "EMBEDDING_DIM", 768),
            embedding_max_tokens=_int(env, "EMBEDDING_MAX_TOKENS", 1024),
            embedding_model=_str(env, "EMBEDDING_MODEL", "google/embeddinggemma-2"),
            qdrant_upsert_batch=_int(env, "QDRANT_UPSERT_BATCH", 64),
            stale_processing_seconds=_int(env, "STALE_PROCESSING_SECONDS", 900),
            sweep_interval_seconds=_int(env, "SWEEP_INTERVAL_SECONDS", 60),
            upload_requeue_after_seconds=_int(env, "UPLOAD_REQUEUE_AFTER_SECONDS", 120),
        )
    except ConfigError as exc:
        get_logger().error("invalid configuration %s", exc)
        raise SystemExit(1) from exc
    try:
        validate_settings(settings)
    except ConfigError as exc:
        get_logger().error("invalid configuration %s", exc)
        raise SystemExit(1) from exc
    return settings


def validate_settings(settings: Settings) -> None:
    if settings.processor_concurrency < 1:
        raise ConfigError("PROCESSOR_CONCURRENCY")
    if settings.chunk_tokens < 1:
        raise ConfigError("CHUNK_TOKENS")
    if settings.chunk_tokens > settings.embedding_max_tokens:
        raise ConfigError("CHUNK_TOKENS")
    if settings.chunk_tokens > LOCAL_ATTENTION_WINDOW:
        raise ConfigError("CHUNK_TOKENS")
    if settings.chunk_overlap_tokens < 0 or settings.chunk_overlap_tokens >= settings.chunk_tokens:
        raise ConfigError("CHUNK_OVERLAP_TOKENS")
    if settings.max_process_attempts < 1:
        raise ConfigError("MAX_PROCESS_ATTEMPTS")
    if settings.min_extracted_chars < 0:
        raise ConfigError("MIN_EXTRACTED_CHARS")
    if settings.ocr_render_dpi < 1:
        raise ConfigError("OCR_RENDER_DPI")
    if settings.ocr_timeout <= 0 or settings.embedding_timeout <= 0:
        raise ConfigError("OCR_TIMEOUT" if settings.ocr_timeout <= 0 else "EMBEDDING_TIMEOUT")
    if settings.ocr_max_attempts < 1:
        raise ConfigError("OCR_MAX_ATTEMPTS")
    if settings.embedding_batch_size < 1:
        raise ConfigError("EMBEDDING_BATCH_SIZE")
    if settings.embedding_dim < 1:
        raise ConfigError("EMBEDDING_DIM")
    if settings.embedding_max_tokens < 1:
        raise ConfigError("EMBEDDING_MAX_TOKENS")
    if settings.qdrant_upsert_batch < 1:
        raise ConfigError("QDRANT_UPSERT_BATCH")
    if settings.sweep_interval_seconds < 1 or settings.upload_requeue_after_seconds < 1:
        raise ConfigError("SWEEP_INTERVAL_SECONDS")
    if not settings.embedding_model:
        raise ConfigError("EMBEDDING_MODEL")


def backoff_seconds(process_attempts: int) -> float:
    return float(min(60, 2**process_attempts))


def _str(env: os._Environ[str] | dict[str, str], name: str, default: str) -> str:
    value = env.get(name)
    if value is None or value == "":
        return default
    return value


def _int(env: os._Environ[str] | dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(name) from exc


def _float(env: os._Environ[str] | dict[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(name) from exc


def _log_level(env: os._Environ[str] | dict[str, str]) -> str:
    raw = env.get("LOG_LEVEL")
    if raw is None or raw == "":
        return "info"
    level = raw.lower()
    if level not in LOG_LEVELS:
        raise ConfigError("LOG_LEVEL")
    return level
