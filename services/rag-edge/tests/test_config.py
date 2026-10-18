import json
from pathlib import Path

import pytest
from rag_edge.config import ENV_NAMES, Settings, load_settings, normalize_base_url
from rag_edge.proxy import select_upstream

ROOT = Path(__file__).resolve().parents[1]


def test_default_upstreams_match_compose_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.rag_edge_port == 8080
    assert settings.max_upload_bytes == 524_288_000
    assert settings.file_collector_url == "http://file-collector:8081"
    assert settings.chat_url == "http://chat:8082"
    assert settings.frontend_url == "http://frontend:3000"
    assert settings.log_level == "info"


def test_route_table_uses_service_prefixes() -> None:
    settings = Settings(
        file_collector_url="http://file-collector:8081",
        chat_url="http://chat:8082",
        frontend_url="http://frontend:3000",
    )
    assert select_upstream("/api/files", settings) == settings.file_collector_url
    assert select_upstream("/api/files/abc/content", settings) == settings.file_collector_url
    assert select_upstream("/api/chats", settings) == settings.chat_url
    assert select_upstream("/api/chats/abc/messages", settings) == settings.chat_url
    assert select_upstream("/", settings) == settings.frontend_url
    assert select_upstream("/assets/index.js", settings) == settings.frontend_url
    assert select_upstream("/api/files-other", settings) == settings.frontend_url
    assert select_upstream("/API/files", settings) == settings.frontend_url


def test_base_url_strips_trailing_slash() -> None:
    assert normalize_base_url("http://file-collector:8081/") == "http://file-collector:8081"


def test_invalid_configuration_logs_variable_name_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FILE_COLLECTOR_URL", "http://user:secret-token@file-collector:8081")
    with pytest.raises(SystemExit):
        load_settings()
    logged = capsys.readouterr().err
    assert "FILE_COLLECTOR_URL" in logged
    assert "secret-token" not in logged
    payload = json.loads(logged.strip().splitlines()[-1])
    assert payload["service"] == "rag-edge"
    assert payload["variable"] == "FILE_COLLECTOR_URL"
    assert "secret-token" not in json.dumps(payload)


def test_container_config_listens_internally_without_host_publish() -> None:
    container = (ROOT / "Containerfile").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile == container
    assert "EXPOSE 8080" in container
    assert container.count("EXPOSE") == 1
    assert "USER nobody" in container
    assert 'CMD ["rag-edge"]' in container
    assert "-p " not in container
    assert "ports:" not in container.lower()
    readme = (ROOT / "README.md").read_text()
    assert "rag_edge" in readme
    assert "rag_internal" in readme
    assert "file-collector" in readme
    assert "text/event-stream" in readme
