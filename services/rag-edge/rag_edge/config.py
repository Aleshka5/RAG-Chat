"""Environment for rag-edge. Defaults match docs/configuration.md and compose DNS names."""

import json
import sys
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_NAMES = {
    "rag_edge_port": "RAG_EDGE_PORT",
    "max_upload_bytes": "MAX_UPLOAD_BYTES",
    "file_collector_url": "FILE_COLLECTOR_URL",
    "chat_url": "CHAT_URL",
    "frontend_url": "FRONTEND_URL",
    "log_level": "LOG_LEVEL",
}

DEFAULT_MAX_UPLOAD_BYTES = 524_288_000


def normalize_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid url")
    raw = value.strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("invalid url")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("invalid url")
    if parts.path not in {"", "/"}:
        raise ValueError("invalid url")
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{host}{port}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    rag_edge_port: int = Field(default=8080, ge=1, le=65535)
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, ge=1)
    file_collector_url: str = "http://file-collector:8081"
    chat_url: str = "http://chat:8082"
    frontend_url: str = "http://frontend:3000"
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator("file_collector_url", "chat_url", "frontend_url", mode="before")
    @classmethod
    def _base_url(cls, value: object) -> str:
        return normalize_base_url(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def _level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        reported: set[str] = set()
        for error in exc.errors():
            loc = error.get("loc") or ()
            field = str(loc[0]) if loc else "configuration"
            variable = ENV_NAMES.get(field, field)
            if variable in reported:
                continue
            reported.add(variable)
            sys.stderr.write(
                json.dumps(
                    {
                        "service": "rag-edge",
                        "level": "error",
                        "message": "invalid configuration",
                        "variable": variable,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        raise SystemExit(1) from None
