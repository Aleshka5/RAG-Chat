import logging
import math
import os
from dataclasses import dataclass

logger = logging.getLogger("chat")

_REQUIRED = (
    "MONGODB_URI",
    "QDRANT_URL",
    "EMBEDDING_URL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
)

_LOG_LEVELS = {"debug", "info", "warning", "error"}


class ConfigError(SystemExit):
    pass


def _fail(name: str) -> None:
    logger.error("missing or invalid environment variable: %s", name, extra={"variable": name})
    raise ConfigError(1)


def _raw(name: str) -> str | None:
    if name not in os.environ:
        return None
    value = os.environ[name].strip()
    if value == "":
        return None
    return value


def _required_str(name: str) -> str:
    value = _raw(name)
    if value is None:
        _fail(name)
    return value


def _optional_str(name: str, default: str) -> str:
    value = _raw(name)
    return default if value is None else value


def _int_value(name: str, default: int, *, minimum: int, maximum: int | None) -> int:
    raw = _raw(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            _fail(name)
    if value < minimum or (maximum is not None and value > maximum):
        _fail(name)
    return value


def _float_value(
    name: str,
    default: float,
    *,
    minimum: float | None,
    maximum: float | None,
) -> float:
    raw = _raw(name)
    if raw is None:
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            _fail(name)
    if not math.isfinite(value):
        _fail(name)
    if minimum is not None and value < minimum:
        _fail(name)
    if maximum is not None and value > maximum:
        _fail(name)
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    mongodb_uri: str
    qdrant_url: str
    qdrant_collection: str
    qdrant_images_collection: str
    embedding_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float
    llm_timeout_seconds: float
    rag_top_k: int
    image_search_cache_ttl_seconds: int
    image_search_cache_size: int
    rag_min_score: float
    rag_context_messages: int
    embedding_timeout: float
    embedding_dim: int
    embedding_max_tokens: int
    chat_port: int
    log_level: str


def load_settings() -> Settings:
    missing = [name for name in _REQUIRED if _raw(name) is None]
    if missing:
        for name in missing:
            logger.error(
                "missing or invalid environment variable: %s",
                name,
                extra={"variable": name},
            )
        raise ConfigError(1)

    log_level = _optional_str("LOG_LEVEL", "info").lower()
    if log_level not in _LOG_LEVELS:
        _fail("LOG_LEVEL")

    return Settings(
        mongodb_uri=_required_str("MONGODB_URI"),
        qdrant_url=_required_str("QDRANT_URL").rstrip("/"),
        qdrant_collection=_optional_str("QDRANT_COLLECTION", "documents"),
        qdrant_images_collection=_optional_str("QDRANT_IMAGES_COLLECTION", "images"),
        embedding_url=_required_str("EMBEDDING_URL").rstrip("/"),
        llm_base_url=_required_str("LLM_BASE_URL").rstrip("/"),
        llm_api_key=_required_str("LLM_API_KEY"),
        llm_model=_required_str("LLM_MODEL"),
        llm_temperature=_float_value("LLM_TEMPERATURE", 0.2, minimum=None, maximum=None),
        llm_timeout_seconds=_float_value("LLM_TIMEOUT_SECONDS", 60, minimum=0.001, maximum=None),
        rag_top_k=_int_value("RAG_TOP_K", 5, minimum=1, maximum=50),
        image_search_cache_ttl_seconds=_int_value(
            "IMAGE_SEARCH_CACHE_TTL_SECONDS", 60, minimum=0, maximum=None
        ),
        image_search_cache_size=_int_value("IMAGE_SEARCH_CACHE_SIZE", 256, minimum=1, maximum=None),
        rag_min_score=_float_value("RAG_MIN_SCORE", 0, minimum=0, maximum=None),
        rag_context_messages=_int_value("RAG_CONTEXT_MESSAGES", 10, minimum=0, maximum=None),
        embedding_timeout=_float_value("EMBEDDING_TIMEOUT", 10, minimum=0.001, maximum=None),
        embedding_dim=_int_value("EMBEDDING_DIM", 768, minimum=1, maximum=None),
        embedding_max_tokens=_int_value("EMBEDDING_MAX_TOKENS", 1024, minimum=1, maximum=None),
        chat_port=_int_value("CHAT_PORT", 8082, minimum=1, maximum=65535),
        log_level=log_level,
    )
