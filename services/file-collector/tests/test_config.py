import os

import pytest
from file_collector.config import Settings
from file_collector.errors import ConfigError

_REQUIRED = {
    "MONGODB_URI": "mongodb://mongo:27017/rag",
    "S3_ENDPOINT": "http://minio:9000",
    "S3_ACCESS_KEY": "access",
    "S3_SECRET_KEY": "super-secret-value",
    "RABBITMQ_URL": "amqp://rabbit:5672/",
}


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(
            (
                "MONGODB_",
                "S3_",
                "RABBITMQ_",
                "FILE_COLLECTOR_",
                "MAX_UPLOAD_",
                "LOG_LEVEL",
                "STALE_",
            )
        ):
            monkeypatch.delenv(name, raising=False)


def test_defaults_and_secret_is_not_in_the_missing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    for name, value in _REQUIRED.items():
        if name != "MONGODB_URI":
            monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError) as caught:
        Settings.from_env()
    assert caught.value.variables == ["MONGODB_URI"]
    assert "super-secret-value" not in str(caught.value)

    monkeypatch.setenv("MONGODB_URI", _REQUIRED["MONGODB_URI"])
    settings = Settings.from_env()
    assert settings.port == 8081
    assert settings.max_upload_bytes == 524288000
    assert settings.s3_bucket == "documents"
    assert settings.s3_region == "us-east-1"
    assert settings.rabbitmq_exchange == "doc_events"
    assert settings.rabbitmq_dlx == "doc_events_dlq"
    assert settings.stale_processing_seconds == 900
    assert settings.log_level == "info"
    assert settings.s3_secret_key == "super-secret-value"


def test_invalid_number_names_the_variable_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    for name, value in _REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "nope")
    with pytest.raises(ConfigError) as caught:
        Settings.from_env()
    assert "MAX_UPLOAD_BYTES" in caught.value.variables
    assert "nope" not in str(caught.value)
    assert "super-secret-value" not in str(caught.value)
