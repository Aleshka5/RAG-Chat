"""Environment names and defaults from docs/configuration.md.

Secrets have no default and are never written into an error message.
A service that lacks a variable it requires does not start.
"""

from collections.abc import Mapping
from typing import Any

SECRET_NAMES = frozenset({"S3_ACCESS_KEY", "S3_SECRET_KEY", "LLM_API_KEY"})

# Documented defaults. Absence means the variable has no default.
DEFAULTS: dict[str, str] = {
    "S3_BUCKET": "documents",
    "S3_REGION": "us-east-1",
    "QDRANT_COLLECTION": "documents",
    "RABBITMQ_EXCHANGE": "doc_events",
    "RABBITMQ_DLX": "doc_events_dlq",
    "LOG_LEVEL": "info",
    "FILE_COLLECTOR_PORT": "8081",
    "MAX_UPLOAD_BYTES": "524288000",
    "PROCESSOR_CONCURRENCY": "1",
    "CHUNK_TOKENS": "512",
    "CHUNK_OVERLAP_TOKENS": "51",
    "MAX_PROCESS_ATTEMPTS": "8",
    "MIN_EXTRACTED_CHARS": "50",
    "OCR_RENDER_DPI": "300",
    "OCR_TIMEOUT": "30",
    "OCR_MAX_ATTEMPTS": "3",
    "EMBEDDING_TIMEOUT": "30",
    "EMBEDDING_BATCH_SIZE": "16",
    "EMBEDDING_DIM": "768",
    "EMBEDDING_MAX_TOKENS": "1024",
    "QDRANT_UPSERT_BATCH": "64",
    "STALE_PROCESSING_SECONDS": "900",
    "SWEEP_INTERVAL_SECONDS": "60",
    "UPLOAD_REQUEUE_AFTER_SECONDS": "120",
    "DELETION_CONCURRENCY": "1",
    "DELETE_REQUEUE_AFTER_SECONDS": "120",
    "CHAT_PORT": "8082",
    "LLM_TEMPERATURE": "0.2",
    "LLM_TIMEOUT_SECONDS": "60",
    "RAG_TOP_K": "5",
    "RAG_MIN_SCORE": "0",
    "RAG_CONTEXT_MESSAGES": "10",
    "OCR_PORT": "8090",
    "OCR_MODEL": "paddleocr_multilingual",
    "EMBEDDING_PORT": "8091",
    "EMBEDDING_MODEL": "google/embeddinggemma-2",
    "EMBEDDING_GGUF": "embeddinggemma-2-Q8_0.gguf",
    "EMBEDDING_LLAMA_URL": "http://127.0.0.1:8092",
    "EMBEDDING_CONTEXT": "2048",
    "RAG_EDGE_PORT": "8080",
    "FILE_COLLECTOR_URL": "http://file-collector:8081",
    "CHAT_URL": "http://chat:8082",
    "FRONTEND_URL": "http://frontend:3000",
}

# Chat's default differs from Processor and Embedding. An explicit env value wins for every process.
CHAT_EMBEDDING_TIMEOUT = "10"

# Processor: CHUNK_TOKENS is not above this local window and not above EMBEDDING_MAX_TOKENS.
LOCAL_MODEL_WINDOW = 1024

LOG_LEVELS = frozenset({"debug", "info", "warning", "error"})

INT_SETTINGS = frozenset(
    {
        "FILE_COLLECTOR_PORT",
        "MAX_UPLOAD_BYTES",
        "PROCESSOR_CONCURRENCY",
        "CHUNK_TOKENS",
        "CHUNK_OVERLAP_TOKENS",
        "MAX_PROCESS_ATTEMPTS",
        "MIN_EXTRACTED_CHARS",
        "OCR_RENDER_DPI",
        "OCR_TIMEOUT",
        "OCR_MAX_ATTEMPTS",
        "EMBEDDING_TIMEOUT",
        "EMBEDDING_BATCH_SIZE",
        "EMBEDDING_DIM",
        "EMBEDDING_MAX_TOKENS",
        "QDRANT_UPSERT_BATCH",
        "STALE_PROCESSING_SECONDS",
        "SWEEP_INTERVAL_SECONDS",
        "UPLOAD_REQUEUE_AFTER_SECONDS",
        "DELETION_CONCURRENCY",
        "DELETE_REQUEUE_AFTER_SECONDS",
        "CHAT_PORT",
        "LLM_TIMEOUT_SECONDS",
        "RAG_TOP_K",
        "RAG_CONTEXT_MESSAGES",
        "OCR_PORT",
        "EMBEDDING_PORT",
        "EMBEDDING_CONTEXT",
        "RAG_EDGE_PORT",
    }
)

FLOAT_SETTINGS = frozenset({"LLM_TEMPERATURE", "RAG_MIN_SCORE"})

# Variables with no default, by the process that needs them (docs/configuration.md).
REQUIRED_BY_SERVICE: dict[str, tuple[str, ...]] = {
    "file-collector": (
        "MONGODB_URI",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "RABBITMQ_URL",
    ),
    "processor": (
        "MONGODB_URI",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "QDRANT_URL",
        "RABBITMQ_URL",
        "EMBEDDING_URL",
        "OCR_URL",
    ),
    "deletion-worker": (
        "MONGODB_URI",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "QDRANT_URL",
        "RABBITMQ_URL",
    ),
    "chat": (
        "MONGODB_URI",
        "QDRANT_URL",
        "EMBEDDING_URL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
    ),
    "ocr": (),
    "embedding": (),
    "rag-edge": (),
    "frontend": (),
}

SERVICE_DEFAULT_OVERRIDES: dict[str, dict[str, str]] = {
    "chat": {"EMBEDDING_TIMEOUT": CHAT_EMBEDDING_TIMEOUT},
}

NO_DEFAULT_NAMES = (
    "MONGODB_URI",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "QDRANT_URL",
    "RABBITMQ_URL",
    "EMBEDDING_URL",
    "OCR_URL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
)


class ConfigError(Exception):
    def __init__(self, names: list[str], message: str) -> None:
        self.names = names
        super().__init__(message)


class MissingConfig(ConfigError):
    def __init__(self, names: list[str]) -> None:
        super().__init__(names, "missing configuration: " + ", ".join(names))


class InvalidConfig(ConfigError):
    def __init__(self, names: list[str]) -> None:
        super().__init__(names, "invalid configuration: " + ", ".join(names))


def config_failure_record(exc: ConfigError) -> dict[str, Any]:
    """Log payload: variable names only, never values."""
    return {"message": "configuration rejected", "variables": list(exc.names)}


def _lookup(name: str, environ: Mapping[str, str], defaults: Mapping[str, str]) -> str | None:
    raw = environ.get(name)
    if raw is not None and raw != "":
        return raw
    if name in defaults:
        return defaults[name]
    return None


def _coerce(name: str, raw: str) -> Any:
    if name in INT_SETTINGS:
        try:
            return int(raw)
        except ValueError as exc:
            raise InvalidConfig([name]) from exc
    if name in FLOAT_SETTINGS:
        try:
            return float(raw)
        except ValueError as exc:
            raise InvalidConfig([name]) from exc
    return raw


def load_config(
    required: tuple[str, ...] | list[str] = (),
    *,
    environ: Mapping[str, str] | None = None,
    defaults: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Load defaults plus ``required`` names.

    Empty string is treated as unset. Secret names are never filled from ``DEFAULTS``.
    """
    env = {} if environ is None else environ
    merged = dict(DEFAULTS)
    if defaults:
        merged.update(defaults)
    for secret in SECRET_NAMES:
        merged.pop(secret, None)

    missing = [name for name in required if _lookup(name, env, merged) is None]
    if missing:
        raise MissingConfig(missing)

    values: dict[str, Any] = {}
    names = list(dict.fromkeys([*merged.keys(), *required, *NO_DEFAULT_NAMES]))
    for name in names:
        raw = _lookup(name, env, merged)
        if raw is None:
            continue
        values[name] = _coerce(name, raw)

    level = values.get("LOG_LEVEL")
    if level is not None and level not in LOG_LEVELS:
        raise InvalidConfig(["LOG_LEVEL"])
    return values


def validate_processor_config(cfg: Mapping[str, Any]) -> None:
    """Refuse to start when chunking does not fit the embedding window."""
    chunk = cfg["CHUNK_TOKENS"]
    overlap = cfg["CHUNK_OVERLAP_TOKENS"]
    limit = cfg["EMBEDDING_MAX_TOKENS"]
    if (
        type(chunk) is not int
        or type(overlap) is not int
        or type(limit) is not int
        or chunk > limit
        or chunk > LOCAL_MODEL_WINDOW
        or overlap >= chunk
    ):
        raise InvalidConfig(["CHUNK_TOKENS", "CHUNK_OVERLAP_TOKENS", "EMBEDDING_MAX_TOKENS"])


def validate_chat_config(cfg: Mapping[str, Any]) -> None:
    top_k = cfg["RAG_TOP_K"]
    if type(top_k) is not int or top_k <= 0 or top_k > 50:
        raise InvalidConfig(["RAG_TOP_K"])


def load_service_config(service: str, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Load configuration for one process and apply that process's startup checks."""
    if service not in REQUIRED_BY_SERVICE:
        raise InvalidConfig([service])
    cfg = load_config(
        REQUIRED_BY_SERVICE[service],
        environ=environ,
        defaults=SERVICE_DEFAULT_OVERRIDES.get(service),
    )
    if service == "processor":
        validate_processor_config(cfg)
    if service == "chat":
        validate_chat_config(cfg)
    return cfg
