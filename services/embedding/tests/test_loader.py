import inspect
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from embedding.app import create_app
from embedding.config import Settings
from embedding.constants import (
    GGUF_REPO,
    GGUF_REVISION,
    MODEL_ID,
    TOKENIZER_FILE,
    TOKENIZER_REPO,
    TOKENIZER_REVISION,
)
from embedding.encoder import ImageInput, LlamaEncoder
from embedding.errors import ModelLoadError, UpstreamFailed
from embedding.loader import (
    LoadedModel,
    build_llama_server_command,
    download_gguf,
    download_tokenizer,
    load_model,
)
from tests.fakes import FakeCounter, FakeEncoder


def test_llama_command_matches_the_embedding_contract() -> None:
    settings = Settings.from_env({})
    mmproj = Path("/models") / settings.mmproj
    command = build_llama_server_command(
        settings,
        Path("/models/embeddinggemma-2-Q8_0.gguf"),
        "llama-server",
        mmproj,
    )
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8092"
    assert command[command.index("-ngl") + 1] == "999"
    assert command.count("-ngl") == 1
    assert command[command.index("--model") + 1].endswith("embeddinggemma-2-Q8_0.gguf")
    assert command[command.index("--mmproj") + 1] == str(mmproj)
    assert command[command.index("--mmproj") + 1].endswith("mmproj-embeddinggemma-2-Q8_0.gguf")
    assert command.count("--mmproj") == 1
    assert "--no-mmproj" not in command
    assert "--embeddings" in command
    assert command[command.index("--pooling") + 1] == "mean"
    assert command[command.index("--ctx-size") + 1] == "2048"
    assert command[command.index("--batch-size") + 1] == "2048"
    assert command[command.index("--ubatch-size") + 1] == "2048"
    assert command[command.index("--parallel") + 1] == "1"
    assert command[command.index("--embd-normalize") + 1] == "2"
    joined = " ".join(command)
    assert "F16" not in joined
    assert "safetensors" not in joined
    assert "audio" not in joined


def test_llama_command_passes_the_configured_gpu_layers() -> None:
    settings = Settings.from_env({"EMBEDDING_LLAMA_NGL": "0"})
    mmproj = Path("/models/mmproj-embeddinggemma-2-Q8_0.gguf")
    command = build_llama_server_command(
        settings,
        Path("/models/embeddinggemma-2-Q8_0.gguf"),
        "llama-server",
        mmproj,
    )
    assert command[command.index("-ngl") + 1] == "0"

    all_layers = Settings.from_env({"EMBEDDING_LLAMA_NGL": "-1"})
    command = build_llama_server_command(
        all_layers,
        Path("/models/embeddinggemma-2-Q8_0.gguf"),
        "llama-server",
        mmproj,
    )
    assert command[command.index("-ngl") + 1] == "-1"


def test_llama_command_uses_the_configured_mmproj_filename() -> None:
    settings = Settings.from_env({"EMBEDDING_MMPROJ": "mmproj-custom-Q8_0.gguf"})
    command = build_llama_server_command(
        settings,
        Path("/models/embeddinggemma-2-Q8_0.gguf"),
        "llama-server",
        Path("/models") / settings.mmproj,
    )
    assert command[command.index("--mmproj") + 1].endswith("mmproj-custom-Q8_0.gguf")
    assert "--no-mmproj" not in command


def test_weight_downloads_use_the_pinned_revisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gguf = tmp_path / "embeddinggemma-2-Q8_0.gguf"
    gguf.write_bytes(b"gguf")
    tokenizer = tmp_path / "tokenizer.json"
    tokenizer.write_bytes(b"{}")
    seen: list[dict[str, str]] = []

    def fake_download(**kwargs: str) -> str:
        seen.append(kwargs)
        if kwargs["filename"] == "tokenizer.json":
            return str(tokenizer)
        return str(gguf)

    monkeypatch.setattr("embedding.loader.hf_hub_download", fake_download)
    assert download_gguf("embeddinggemma-2-Q8_0.gguf") == gguf
    assert download_tokenizer() == tokenizer
    assert seen[0]["repo_id"] == GGUF_REPO
    assert seen[0]["revision"] == GGUF_REVISION
    assert seen[0]["filename"] == "embeddinggemma-2-Q8_0.gguf"
    assert seen[1]["repo_id"] == TOKENIZER_REPO
    assert seen[1]["revision"] == TOKENIZER_REVISION
    assert seen[1]["filename"] == TOKENIZER_FILE


def test_load_model_starts_llama_server_when_it_is_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings.from_env({})
    downloaded: list[str] = []

    def fake_download(filename: str) -> Path:
        downloaded.append(filename)
        path = tmp_path / filename
        path.write_bytes(b"gguf")
        return path

    monkeypatch.setattr("embedding.loader.download_gguf", fake_download)
    monkeypatch.setattr("embedding.loader.download_tokenizer", lambda: tmp_path / "tokenizer.json")
    monkeypatch.setattr(
        "embedding.loader.TokenizerJsonCounter.from_file", lambda _path: FakeCounter(1)
    )
    monkeypatch.setattr("embedding.loader.shutil.which", lambda _name: "/opt/llama/llama-server")
    checks = {"n": 0}

    def healthy(_url: str, timeout: float) -> bool:
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr("embedding.loader._llama_is_healthy", healthy)
    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

    def fake_popen(command: list[str]) -> FakeProcess:
        commands.append(command)
        return FakeProcess()

    monkeypatch.setattr("embedding.loader.subprocess.Popen", fake_popen)
    loaded = load_model(settings)
    assert downloaded == [settings.gguf, settings.mmproj]
    assert len(commands) == 1
    assert "--embeddings" in commands[0]
    assert commands[0][commands[0].index("--pooling") + 1] == "mean"
    assert commands[0][commands[0].index("--mmproj") + 1].endswith(settings.mmproj)
    assert "--no-mmproj" not in commands[0]
    assert commands[0][0] == "/opt/llama/llama-server"
    assert isinstance(loaded.encoder, LlamaEncoder)
    loaded.close()


def test_load_model_does_not_spawn_a_second_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("embedding.loader.download_gguf", lambda _filename: tmp_path / "m.gguf")
    monkeypatch.setattr("embedding.loader.download_tokenizer", lambda: tmp_path / "tokenizer.json")
    monkeypatch.setattr(
        "embedding.loader.TokenizerJsonCounter.from_file", lambda _path: FakeCounter(1)
    )
    monkeypatch.setattr("embedding.loader._llama_is_healthy", lambda _url, timeout: True)
    monkeypatch.setattr(
        "embedding.loader.subprocess.Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("spawned")),
    )
    loaded = load_model(Settings.from_env({}))
    assert isinstance(loaded.encoder, LlamaEncoder)
    loaded.close()


def test_llama_command_omits_mmproj_when_the_projector_file_is_missing() -> None:
    settings = Settings.from_env({})
    command = build_llama_server_command(
        settings,
        Path("/models/embeddinggemma-2-Q8_0.gguf"),
        "llama-server",
        None,
    )
    assert "--mmproj" not in command
    assert "--no-mmproj" not in command
    assert "--embeddings" in command


def test_missing_mmproj_keeps_text_startup_and_disables_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_download(filename: str) -> Path:
        if "mmproj" in filename:
            raise ModelLoadError("failed to download EMBEDDING_MMPROJ")
        path = tmp_path / filename
        path.write_bytes(b"gguf")
        return path

    monkeypatch.setattr("embedding.loader.download_gguf", fake_download)
    monkeypatch.setattr("embedding.loader.download_tokenizer", lambda: tmp_path / "tokenizer.json")
    monkeypatch.setattr(
        "embedding.loader.TokenizerJsonCounter.from_file", lambda _path: FakeCounter(1)
    )
    monkeypatch.setattr("embedding.loader.shutil.which", lambda _name: "llama-server")
    checks = {"n": 0}

    def healthy(_url: str, timeout: float) -> bool:
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr("embedding.loader._llama_is_healthy", healthy)
    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "embedding.loader.subprocess.Popen",
        lambda command: commands.append(command) or FakeProcess(),
    )
    loaded = load_model(Settings.from_env({}))
    assert len(commands) == 1
    assert "--embeddings" in commands[0]
    assert "--mmproj" not in commands[0]
    assert "--no-mmproj" not in commands[0]
    assert loaded.encoder.images_ready is False
    with pytest.raises(UpstreamFailed):
        loaded.encoder.embed_images([ImageInput("image/png", "iVBORw0KGgo=")])
    loaded.close()


def test_download_gguf_fails_when_the_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "mmproj-embeddinggemma-2-Q8_0.gguf"

    def fake_download(**kwargs: str) -> str:
        assert kwargs["filename"] == missing.name
        return str(missing)

    monkeypatch.setattr("embedding.loader.hf_hub_download", fake_download)
    with pytest.raises(ModelLoadError, match="EMBEDDING_MMPROJ"):
        download_gguf(missing.name)


def test_load_model_stops_the_container_when_llama_exits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("embedding.loader.download_gguf", lambda _filename: tmp_path / "m.gguf")
    monkeypatch.setattr("embedding.loader.download_tokenizer", lambda: tmp_path / "tokenizer.json")
    monkeypatch.setattr(
        "embedding.loader.TokenizerJsonCounter.from_file", lambda _path: FakeCounter(1)
    )
    monkeypatch.setattr("embedding.loader.shutil.which", lambda _name: "llama-server")
    monkeypatch.setattr("embedding.loader._llama_is_healthy", lambda _url, timeout: False)

    class DeadProcess:
        def poll(self) -> int:
            return 1

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 1

    monkeypatch.setattr("embedding.loader.subprocess.Popen", lambda _command: DeadProcess())
    with pytest.raises(ModelLoadError):
        load_model(Settings.from_env({}))


def test_startup_calls_the_real_loader_before_health(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def fake_load(settings: Settings) -> LoadedModel:
        order.append("load")
        assert settings.model == MODEL_ID
        return LoadedModel(encoder=FakeEncoder(), token_counter=FakeCounter(1))

    monkeypatch.setattr("embedding.app.load_model", fake_load)
    app = create_app(Settings.from_env({}))
    with TestClient(app) as client:
        order.append("ready")
        response = client.get("/health")
    assert order == ["load", "ready"]
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_failed_load_prevents_healthy_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load(_settings: Settings) -> LoadedModel:
        raise ModelLoadError("llama-server exited during load")

    monkeypatch.setattr("embedding.app.load_model", fake_load)
    app = create_app(Settings.from_env({}))
    with pytest.raises(ModelLoadError):
        with TestClient(app):
            pass


def test_production_modules_call_the_real_loader() -> None:
    import embedding.__main__ as entry
    import embedding.app as app_module
    import embedding.loader as loader

    assert "load_model(" in inspect.getsource(app_module.create_app)
    assert "create_app(settings)" in inspect.getsource(entry.main)
    assert "encoder=" not in inspect.getsource(entry.main)
    loader_source = Path(loader.__file__).read_text(encoding="utf-8")
    assert "subprocess.Popen" in loader_source
    assert "hf_hub_download" in loader_source
    assert "torch" not in loader_source
    assert "sentence_transformers" not in loader_source
    assert "safetensors" not in loader_source


def test_llama_encoder_orders_vectors_and_forwards_request_id() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        seen["request_id"] = request.headers.get("x-request-id")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8092")
    encoder = LlamaEncoder("http://127.0.0.1:8092", 30, client=client)
    vectors = encoder.embed(["first", "second"], request_id="6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f")
    assert seen["path"] == "/v1/embeddings"
    assert '"encoding_format":"float"' in str(seen["body"]).replace(" ", "")
    assert seen["request_id"] == "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    encoder.close()


def test_llama_encoder_timeout_and_bad_payload() -> None:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    slow = LlamaEncoder(
        "http://127.0.0.1:8092",
        30,
        client=httpx.Client(
            transport=httpx.MockTransport(timeout), base_url="http://127.0.0.1:8092"
        ),
    )
    with pytest.raises(Exception) as timed_out:
        slow.embed(["text"])
    assert timed_out.value.__class__.__name__ == "UpstreamTimeout"
    slow.close()

    def bad(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": "nope"}]})

    broken = LlamaEncoder(
        "http://127.0.0.1:8092",
        30,
        client=httpx.Client(transport=httpx.MockTransport(bad), base_url="http://127.0.0.1:8092"),
    )
    with pytest.raises(UpstreamFailed):
        broken.embed(["text"])
    broken.close()
