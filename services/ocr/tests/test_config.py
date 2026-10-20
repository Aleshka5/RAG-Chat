from __future__ import annotations

import logging

import pytest

from ocr_service.config import MODEL_NAME, ConfigError, Settings
from ocr_service.main import main


def test_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OCR_PORT", "OCR_MODEL", "OCR_TIMEOUT", "OCR_LLAMA_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.ocr_port == 8090
    assert settings.ocr_model == MODEL_NAME
    assert settings.ocr_timeout == 120
    assert settings.llama_url == "http://127.0.0.1:8092"
    assert settings.log_level == "info"


def test_explicit_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR_PORT", "8090")
    monkeypatch.setenv("OCR_MODEL", "surya-ocr-2")
    monkeypatch.setenv("OCR_TIMEOUT", "60")
    monkeypatch.setenv("OCR_LLAMA_URL", "http://127.0.0.1:8092/")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings.from_env()
    assert settings.ocr_port == 8090
    assert settings.ocr_model == "surya-ocr-2"
    assert settings.ocr_timeout == 60
    assert settings.llama_url == "http://127.0.0.1:8092"
    assert settings.log_level == "debug"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OCR_PORT", "0"),
        ("OCR_PORT", "70000"),
        ("OCR_PORT", "abc"),
        ("OCR_PORT", ""),
        ("OCR_MODEL", "other"),
        ("OCR_MODEL", ""),
        ("OCR_LLAMA_URL", ""),
        ("OCR_LLAMA_URL", "notaurl"),
        ("OCR_LLAMA_URL", "http://127.0.0.1:8092/v1"),
        ("OCR_TIMEOUT", "0"),
        ("OCR_TIMEOUT", "-1"),
        ("OCR_TIMEOUT", "nope"),
        ("OCR_TIMEOUT", ""),
        ("LOG_LEVEL", "verbose"),
        ("LOG_LEVEL", ""),
    ],
)
def test_invalid_value_names_only_the_variable(name: str, value: str) -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(name, value)
    try:
        with pytest.raises(ConfigError) as exc_info:
            Settings.from_env()
    finally:
        monkeypatch.undo()
    assert exc_info.value.name == name
    assert value not in str(exc_info.value) or value == ""


def test_main_logs_variable_name_without_value(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OCR_TIMEOUT", "not-a-number")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert "OCR_TIMEOUT" in caplog.text
    assert "not-a-number" not in caplog.text
