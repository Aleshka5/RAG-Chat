"""Process configuration for the OCR service."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

MODEL_NAME = "paddleocr_multilingual"
DEFAULT_PORT = 8090
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LOG_LEVEL = "info"
LOG_LEVELS = ("debug", "info", "warning", "error")


class ConfigError(Exception):
    """A required setting is missing or not usable.

    The message is only the variable name. The value is never included.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)


@dataclass(frozen=True, slots=True)
class Settings:
    ocr_port: int = DEFAULT_PORT
    ocr_model: str = MODEL_NAME
    ocr_timeout: float = DEFAULT_TIMEOUT_SECONDS
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            ocr_port=_port(os.environ.get("OCR_PORT")),
            ocr_model=_model(os.environ.get("OCR_MODEL")),
            ocr_timeout=_timeout(os.environ.get("OCR_TIMEOUT")),
            log_level=_log_level(os.environ.get("LOG_LEVEL")),
        )


def _present(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if value == "":
        return ""
    return value


def _port(raw: str | None) -> int:
    value = _present(raw)
    if value is None:
        return DEFAULT_PORT
    if value == "":
        raise ConfigError("OCR_PORT")
    try:
        port = int(value)
    except ValueError:
        raise ConfigError("OCR_PORT") from None
    if port < 1 or port > 65535:
        raise ConfigError("OCR_PORT")
    return port


def _model(raw: str | None) -> str:
    value = _present(raw)
    if value is None:
        return MODEL_NAME
    if value != MODEL_NAME:
        raise ConfigError("OCR_MODEL")
    return value


def _timeout(raw: str | None) -> float:
    value = _present(raw)
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if value == "":
        raise ConfigError("OCR_TIMEOUT")
    try:
        timeout = float(value)
    except ValueError:
        raise ConfigError("OCR_TIMEOUT") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigError("OCR_TIMEOUT")
    return timeout


def _log_level(raw: str | None) -> str:
    value = _present(raw)
    if value is None:
        return DEFAULT_LOG_LEVEL
    if value == "":
        raise ConfigError("LOG_LEVEL")
    level = value.lower()
    if level not in LOG_LEVELS:
        raise ConfigError("LOG_LEVEL")
    return level
