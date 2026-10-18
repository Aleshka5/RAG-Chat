import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from embedding.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONTEXT,
    DEFAULT_DIMENSION,
    DEFAULT_GGUF,
    DEFAULT_LLAMA_URL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT_SECONDS,
    MODEL_ID,
)
from embedding.errors import ConfigError

_LOG_LEVELS = {"debug", "info", "warning", "error"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


@dataclass(frozen=True)
class Settings:
    port: int
    model: str
    gguf: str
    llama_url: str
    llama_host: str
    llama_port: int
    context: int
    dimension: int
    max_tokens: int
    batch_size: int
    timeout_seconds: float
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        port = _positive_int(source, "EMBEDDING_PORT", DEFAULT_PORT, maximum=65535)
        model = _non_empty(source, "EMBEDDING_MODEL", MODEL_ID)
        gguf = _gguf_name(source, "EMBEDDING_GGUF", DEFAULT_GGUF)
        llama_url, llama_host, llama_port = _llama_url(
            source,
            "EMBEDDING_LLAMA_URL",
            DEFAULT_LLAMA_URL,
        )
        context = _positive_int(source, "EMBEDDING_CONTEXT", DEFAULT_CONTEXT)
        dimension = _positive_int(source, "EMBEDDING_DIM", DEFAULT_DIMENSION)
        max_tokens = _positive_int(source, "EMBEDDING_MAX_TOKENS", DEFAULT_MAX_TOKENS)
        batch_size = _positive_int(source, "EMBEDDING_BATCH_SIZE", DEFAULT_BATCH_SIZE)
        timeout_seconds = _positive_float(source, "EMBEDDING_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
        log_level = _log_level(source, "LOG_LEVEL", DEFAULT_LOG_LEVEL)
        if context < max_tokens:
            raise ConfigError("EMBEDDING_CONTEXT")
        return cls(
            port=port,
            model=model,
            gguf=gguf,
            llama_url=llama_url,
            llama_host=llama_host,
            llama_port=llama_port,
            context=context,
            dimension=dimension,
            max_tokens=max_tokens,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            log_level=log_level,
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def _raw(env: Mapping[str, str], name: str) -> str | None:
    if name not in env:
        return None
    return env[name]


def _non_empty(env: Mapping[str, str], name: str, default: str) -> str:
    raw = _raw(env, name)
    if raw is None:
        return default
    if raw.strip() == "":
        raise ConfigError(name)
    return raw


def _positive_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    maximum: int | None = None,
) -> int:
    raw = _raw(env, name)
    if raw is None:
        value = default
    else:
        if raw.strip() == "":
            raise ConfigError(name)
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError(name) from exc
    if value < 1 or (maximum is not None and value > maximum):
        raise ConfigError(name)
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _raw(env, name)
    if raw is None:
        value = default
    else:
        if raw.strip() == "":
            raise ConfigError(name)
        try:
            value = float(raw)
        except ValueError as exc:
            raise ConfigError(name) from exc
    if value <= 0:
        raise ConfigError(name)
    return value


def _log_level(env: Mapping[str, str], name: str, default: str) -> str:
    raw = _raw(env, name)
    if raw is None:
        return default
    level = raw.strip().lower()
    if level not in _LOG_LEVELS:
        raise ConfigError(name)
    return level


def _gguf_name(env: Mapping[str, str], name: str, default: str) -> str:
    raw = _raw(env, name)
    filename = default if raw is None else raw
    if filename.strip() == "" or filename != filename.strip():
        raise ConfigError(name)
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ConfigError(name)
    if not filename.lower().endswith(".gguf"):
        raise ConfigError(name)
    parts = filename.lower().replace(".", "-").split("-")
    if "mmproj" in parts or "f16" in parts:
        raise ConfigError(name)
    return filename


def _llama_url(env: Mapping[str, str], name: str, default: str) -> tuple[str, str, int]:
    raw = _raw(env, name)
    if raw is None:
        url = default
    else:
        if raw.strip() == "":
            raise ConfigError(name)
        url = raw.strip()
    parts = urlsplit(url)
    host = parts.hostname
    if parts.scheme not in {"http", "https"} or host not in _LOOPBACK_HOSTS or parts.port is None:
        raise ConfigError(name)
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username:
        raise ConfigError(name)
    normalized = f"{parts.scheme}://{host}:{parts.port}"
    return normalized, host, parts.port
