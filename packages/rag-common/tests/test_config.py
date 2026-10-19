import json
from pathlib import Path

import pytest

from rag_common.config import (
    DEFAULTS,
    SECRET_NAMES,
    InvalidConfig,
    MissingConfig,
    config_failure_record,
    load_config,
    load_service_config,
    validate_chat_config,
    validate_processor_config,
)

ROOT = Path(__file__).resolve().parents[3]


def test_embedding_batch_default_is_16() -> None:
    assert DEFAULTS["EMBEDDING_BATCH_SIZE"] == "16"
    assert DEFAULTS["EMBEDDING_DIM"] == "768"
    assert DEFAULTS["MAX_UPLOAD_BYTES"] == "524288000"
    assert DEFAULTS["CHUNK_TOKENS"] == "512"
    assert DEFAULTS["CHUNK_OVERLAP_TOKENS"] == "51"
    for name in SECRET_NAMES:
        assert name not in DEFAULTS


def test_missing_secret_names_the_variable_only() -> None:
    secret = "not-a-real-key"
    with pytest.raises(MissingConfig) as caught:
        load_service_config(
            "chat",
            {
                "MONGODB_URI": "mongodb://mongo:27017/rag",
                "QDRANT_URL": "http://qdrant:6333",
                "EMBEDDING_URL": "http://embedding:8091",
                "LLM_BASE_URL": "http://llm/v1",
                "LLM_MODEL": "demo",
                "S3_SECRET_KEY": secret,
            },
        )
    assert caught.value.names == ["LLM_API_KEY"]
    record = json.dumps(config_failure_record(caught.value))
    assert "LLM_API_KEY" in record
    assert secret not in record
    assert secret not in str(caught.value)


def test_service_timeout_defaults_and_override() -> None:
    chat = load_service_config(
        "chat",
        {
            "MONGODB_URI": "mongodb://mongo:27017/rag",
            "QDRANT_URL": "http://qdrant:6333",
            "EMBEDDING_URL": "http://embedding:8091",
            "LLM_BASE_URL": "http://llm/v1",
            "LLM_API_KEY": "local-only",
            "LLM_MODEL": "demo",
        },
    )
    assert chat["EMBEDDING_TIMEOUT"] == 10
    assert chat["RAG_TOP_K"] == 5
    assert chat["LLM_TEMPERATURE"] == 0.2
    assert "local-only" not in json.dumps(config_failure_record(InvalidConfig(["RAG_TOP_K"])))

    processor = load_service_config(
        "processor",
        {
            "MONGODB_URI": "mongodb://mongo:27017/rag",
            "S3_ENDPOINT": "http://minio:9000",
            "S3_ACCESS_KEY": "minio",
            "S3_SECRET_KEY": "minio-secret",
            "QDRANT_URL": "http://qdrant:6333",
            "RABBITMQ_URL": "amqp://rabbit:5672/",
            "EMBEDDING_URL": "http://embedding:8091",
            "OCR_URL": "http://ocr:8090",
        },
    )
    assert processor["EMBEDDING_TIMEOUT"] == 30
    assert processor["EMBEDDING_BATCH_SIZE"] == 16
    assert processor["QDRANT_COLLECTION"] == "documents"
    assert processor["RABBITMQ_EXCHANGE"] == "doc_events"

    overridden = load_service_config(
        "chat",
        {
            "MONGODB_URI": "mongodb://mongo:27017/rag",
            "QDRANT_URL": "http://qdrant:6333",
            "EMBEDDING_URL": "http://embedding:8091",
            "LLM_BASE_URL": "http://llm/v1",
            "LLM_API_KEY": "local-only",
            "LLM_MODEL": "demo",
            "EMBEDDING_TIMEOUT": "12",
        },
    )
    assert overridden["EMBEDDING_TIMEOUT"] == 12


def test_processor_refuses_chunk_window() -> None:
    cfg = load_config()
    cfg["CHUNK_TOKENS"] = 2048
    with pytest.raises(InvalidConfig) as caught:
        validate_processor_config(cfg)
    assert "CHUNK_TOKENS" in caught.value.names
    assert "2048" not in str(caught.value)


def test_chat_top_k_bounds() -> None:
    cfg = load_config()
    cfg["RAG_TOP_K"] = 0
    with pytest.raises(InvalidConfig):
        validate_chat_config(cfg)
    cfg["RAG_TOP_K"] = 51
    with pytest.raises(InvalidConfig):
        validate_chat_config(cfg)
    cfg["RAG_TOP_K"] = 50
    validate_chat_config(cfg)


def test_log_level_and_empty_string() -> None:
    with pytest.raises(InvalidConfig) as caught:
        load_config(environ={"LOG_LEVEL": "trace"})
    assert caught.value.names == ["LOG_LEVEL"]
    loaded = load_config(environ={"LOG_LEVEL": ""})
    assert loaded["LOG_LEVEL"] == "info"


def test_ocr_starts_from_defaults() -> None:
    cfg = load_service_config("ocr", {})
    assert cfg["OCR_PORT"] == 8090
    assert cfg["OCR_MODEL"] == "surya-ocr-2"
    assert cfg["OCR_LLAMA_URL"] == "http://127.0.0.1:8092"
    assert cfg["OCR_TIMEOUT"] == 600
    assert cfg["EMBEDDING_MODEL"] == "google/embeddinggemma-2"
    assert cfg["EMBEDDING_GGUF"] == "embeddinggemma-2-Q8_0.gguf"


def test_env_example_lists_every_name_and_blank_secrets() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for line in example.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        found[name] = value
    expected = set(DEFAULTS) | {
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
    }
    assert expected <= set(found)
    assert found["S3_ACCESS_KEY"] == ""
    assert found["S3_SECRET_KEY"] == ""
    assert found["LLM_API_KEY"] == ""
    assert found["EMBEDDING_BATCH_SIZE"] == "16"
