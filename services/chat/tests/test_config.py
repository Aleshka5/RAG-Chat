import logging

import pytest

from chat.config import ConfigError, load_settings
from chat.textutil import (
    NOT_FOUND,
    QUERY_PREFIX,
    estimate_tokens,
    snippet,
    title_from_question,
    truncate_query,
)


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/rag")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("EMBEDDING_URL", "http://embedding:8091")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm:4000/v1/")
    monkeypatch.setenv("LLM_API_KEY", "super-secret-value")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_missing_variable_exits_without_logging_secrets(monkeypatch, caplog):
    _set_required(monkeypatch)
    monkeypatch.delenv("LLM_API_KEY")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ConfigError):
            load_settings()
    assert "LLM_API_KEY" in caplog.text
    assert "super-secret-value" not in caplog.text


def test_invalid_top_k_exits_without_logging_the_key(monkeypatch, caplog):
    _set_required(monkeypatch)
    monkeypatch.setenv("RAG_TOP_K", "51")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ConfigError):
            load_settings()
    assert "RAG_TOP_K" in caplog.text
    assert "super-secret-value" not in caplog.text


def test_defaults_and_trailing_slash(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/rag")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333/")
    monkeypatch.setenv("EMBEDDING_URL", "http://embedding:8091/")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm:4000/v1/")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    settings = load_settings()
    assert settings.chat_port == 8082
    assert settings.rag_top_k == 5
    assert settings.rag_min_score == 0
    assert settings.embedding_dim == 768
    assert settings.llm_temperature == 0.2
    assert settings.llm_base_url == "http://llm:4000/v1"
    assert settings.embedding_url == "http://embedding:8091"
    assert settings.qdrant_url == "http://qdrant:6333"
    assert settings.qdrant_collection == "documents"


def test_title_snippet_and_token_budget():
    assert title_from_question("  a \n b  ") == "a b"
    assert title_from_question("а" * 80) == "а" * 80
    assert title_from_question("а" * 81) == ("а" * 77) + "..."
    assert snippet("x" * 500) == "x" * 500
    assert snippet("x" * 501) == ("x" * 497) + "..."
    question = "я" * 5000
    trimmed = truncate_query(question, 1024)
    assert len(trimmed) < len(question)
    assert estimate_tokens(QUERY_PREFIX + trimmed) <= 1024
    assert NOT_FOUND == "Не найдено в документах."
