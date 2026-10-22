"""Load the text-only EmbeddingGemma 2 GGUF and wait until llama-server is ready.

The hot path is llama.cpp. PyTorch is not used. Image and audio projectors
are not downloaded and are not passed to the server.
"""

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

from embedding.config import Settings
from embedding.constants import (
    GGUF_REPO,
    GGUF_REVISION,
    LOAD_TIMEOUT_SECONDS,
    TOKENIZER_FILE,
    TOKENIZER_REPO,
    TOKENIZER_REVISION,
)
from embedding.encoder import LlamaEncoder, TextEncoder
from embedding.errors import ModelLoadError
from embedding.tokens import TokenCounter, TokenizerJsonCounter

log = logging.getLogger("embedding.loader")


@dataclass
class LoadedModel:
    encoder: TextEncoder
    token_counter: TokenCounter

    def close(self) -> None:
        self.encoder.close()


def load_model(settings: Settings) -> LoadedModel:
    """Download the pinned text GGUF, start llama-server, and block until it is healthy."""
    log.info("loading embedding model %s", settings.model)
    try:
        tokenizer_path = download_tokenizer()
        token_counter = TokenizerJsonCounter.from_file(tokenizer_path)
        model_path = download_gguf(settings.gguf)
    except ModelLoadError:
        raise
    except Exception as exc:
        log.error("failed to download embedding weights")
        raise ModelLoadError("failed to download embedding weights") from exc

    if _llama_is_healthy(settings.llama_url, timeout=2.0):
        log.info("llama-server is already healthy at %s", settings.llama_url)
        encoder = LlamaEncoder(settings.llama_url, settings.timeout_seconds)
        return LoadedModel(encoder=encoder, token_counter=token_counter)

    binary = shutil.which("llama-server")
    if binary is None:
        log.error("llama-server is not on PATH")
        raise ModelLoadError("llama-server is not on PATH")
    command = build_llama_server_command(settings, model_path, binary)
    log.info("starting llama-server")
    process = subprocess.Popen(command)
    try:
        _wait_until_healthy(settings.llama_url, process, LOAD_TIMEOUT_SECONDS)
    except Exception:
        _stop_process(process)
        raise
    encoder = LlamaEncoder(settings.llama_url, settings.timeout_seconds, process=process)
    log.info("embedding model is ready")
    return LoadedModel(encoder=encoder, token_counter=token_counter)


def build_llama_server_command(settings: Settings, model_path: Path, binary: str) -> list[str]:
    context = str(settings.context)
    return [
        binary,
        "--host",
        settings.llama_host,
        "--port",
        str(settings.llama_port),
        # 999 = every layer on the GPU (-1 is the upstream synonym); a CPU-only
        # build ignores the flag, so the same argv serves both image targets.
        "-ngl",
        str(settings.ngl),
        "--model",
        str(model_path),
        "--embeddings",
        "--pooling",
        "mean",
        "--ctx-size",
        context,
        "--batch-size",
        context,
        "--ubatch-size",
        context,
        "--parallel",
        "1",
        "--no-mmproj",
        "--embd-normalize",
        "2",
    ]


def download_gguf(filename: str) -> Path:
    path = Path(
        hf_hub_download(
            repo_id=GGUF_REPO,
            filename=filename,
            revision=GGUF_REVISION,
        )
    )
    if not path.is_file():
        raise ModelLoadError("failed to download EMBEDDING_GGUF")
    return path


def download_tokenizer() -> Path:
    path = Path(
        hf_hub_download(
            repo_id=TOKENIZER_REPO,
            filename=TOKENIZER_FILE,
            revision=TOKENIZER_REVISION,
        )
    )
    if not path.is_file():
        raise ModelLoadError("failed to download tokenizer.json")
    return path


def _llama_is_healthy(url: str, timeout: float) -> bool:
    encoder = LlamaEncoder(url, timeout)
    try:
        return encoder.healthy()
    finally:
        encoder.close()


def _wait_until_healthy(url: str, process: subprocess.Popen[bytes], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            log.error("llama-server exited during load")
            raise ModelLoadError("llama-server exited during load")
        if _llama_is_healthy(url, timeout=2.0):
            return
        if time.monotonic() >= deadline:
            log.error("llama-server did not become healthy")
            raise ModelLoadError("llama-server did not become healthy")
        time.sleep(0.5)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
