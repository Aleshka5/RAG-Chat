import logging

import pytest

from deletion_worker.config import load_settings

_SECRET = "super-secret-value"


def _env() -> dict[str, str]:
    return {
        "MONGODB_URI": "mongodb://mongo:27017/rag",
        "S3_ENDPOINT": "http://minio:9000",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": _SECRET,
        "QDRANT_URL": "http://qdrant:6333",
        "RABBITMQ_URL": "amqp://rabbit:5672/",
    }


def test_defaults(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    settings = load_settings(_env())
    assert settings.s3_bucket == "documents"
    assert settings.s3_region == "us-east-1"
    assert settings.qdrant_collection == "documents"
    assert settings.rabbitmq_exchange == "doc_events"
    assert settings.rabbitmq_dlx == "doc_events_dlq"
    assert settings.log_level == "info"
    assert settings.deletion_concurrency == 1
    assert settings.stale_processing_seconds == 900
    assert settings.sweep_interval_seconds == 60
    assert settings.delete_requeue_after_seconds == 120
    assert _SECRET not in caplog.text


def test_missing_variable_logs_name_without_secret(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    env = _env()
    del env["MONGODB_URI"]
    with pytest.raises(SystemExit):
        load_settings(env)
    assert "MONGODB_URI" in caplog.text
    assert _SECRET not in caplog.text
    assert "amqp://rabbit" not in caplog.text


def test_invalid_concurrency_exits(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    env = _env()
    env["DELETION_CONCURRENCY"] = "0"
    with pytest.raises(SystemExit):
        load_settings(env)
    assert "DELETION_CONCURRENCY" in caplog.text
    assert _SECRET not in caplog.text
