"""Download Surya OCR 2 GGUF weights and run them in llama-server.

The server is not given a thread count or a memory cap (`--cache-ram -1`).
llama.cpp uses the cores the machine gives it. Context is only wide enough
that a fitted page and a full completion are not cut off.
"""

from __future__ import annotations

import base64
import io
import logging
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from huggingface_hub import hf_hub_download
from PIL import Image

from ocr_service.config import Settings
from ocr_service.engine import (
    IMAGE_MIN_TOKENS,
    MAX_NEW_TOKENS,
    PAGE_CONTEXT,
    PageReader,
    mean_token_probability,
)

logger = logging.getLogger("ocr")

GGUF_REPO = "datalab-to/surya-ocr-2-gguf"
GGUF_REVISION = "6a3a4c30e5e74446d4f8b6afd05b2f2da970f470"
GGUF_MODEL = "surya-2.gguf"
GGUF_MMPROJ = "surya-2-mmproj.gguf"
MODEL_ALIAS = "datalab-to/surya-ocr-2"
LOAD_TIMEOUT_SECONDS = 600.0


class ModelLoadError(Exception):
    """Weights or llama-server did not become usable."""


class LlamaReader(PageReader):
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        client: httpx.Client | None = None,
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._timeout = timeout_seconds
        self._process = process

    def complete(
        self,
        image: Image.Image,
        prompt: str,
        *,
        temperature: float,
    ) -> tuple[str, float | None]:
        payload = {
            "model": MODEL_ALIAS,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(image)}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": MAX_NEW_TOKENS,
            "temperature": temperature,
            "top_p": 0.1,
            "logprobs": True,
        }
        try:
            response = self._client.post(
                "/v1/chat/completions",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("llama-server request failed") from exc
        if response.status_code != 200:
            raise RuntimeError("llama-server request failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("llama-server request failed") from exc
        return _completion(body)

    def healthy(self) -> bool:
        try:
            response = self._client.get("/health", timeout=2.0)
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        try:
            body = response.json()
        except ValueError:
            return False
        return isinstance(body, dict) and body.get("status") == "ok"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def start_reader(settings: Settings) -> LlamaReader:
    """Download the GGUF pair if needed and block until llama-server is healthy."""
    reader = LlamaReader(settings.llama_url, settings.ocr_timeout)
    if reader.healthy():
        logger.info("llama-server is already healthy")
        return reader
    reader.close()
    binary = shutil.which("llama-server")
    if binary is None:
        logger.error("llama-server is not on PATH")
        raise ModelLoadError("llama-server is not on PATH")
    try:
        model_path = _download(GGUF_MODEL)
        mmproj_path = _download(GGUF_MMPROJ)
    except ModelLoadError:
        raise
    except Exception as exc:
        logger.error("failed to download OCR weights")
        raise ModelLoadError("failed to download OCR weights") from exc
    host, port = bind_address(settings.llama_url)
    command = build_llama_server_command(
        binary=binary,
        model_path=model_path,
        mmproj_path=mmproj_path,
        host=host,
        port=port,
    )
    logger.info("starting llama-server")
    process = subprocess.Popen(command)
    reader = LlamaReader(settings.llama_url, settings.ocr_timeout, process=process)
    try:
        _wait_until_healthy(reader, process, LOAD_TIMEOUT_SECONDS)
    except Exception:
        reader.close()
        raise
    logger.info("OCR model is ready")
    return reader


def build_llama_server_command(
    *,
    binary: str,
    model_path: Path,
    mmproj_path: Path,
    host: str,
    port: int,
) -> list[str]:
    """Flags Surya needs. No thread count and no memory ceiling."""
    return [
        binary,
        "--host",
        host,
        "--port",
        str(port),
        "--model",
        str(model_path),
        "--mmproj",
        str(mmproj_path),
        "--alias",
        MODEL_ALIAS,
        "--jinja",
        "--ctx-size",
        str(PAGE_CONTEXT),
        "--image-min-tokens",
        str(IMAGE_MIN_TOKENS),
        "--cache-ram",
        "-1",
        "-ngl",
        "999",
    ]


def bind_address(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return host, port


def _download(filename: str) -> Path:
    path = Path(
        hf_hub_download(
            repo_id=GGUF_REPO,
            filename=filename,
            revision=GGUF_REVISION,
        )
    )
    if not path.is_file():
        raise ModelLoadError("failed to download OCR weights")
    return path


def _wait_until_healthy(
    reader: LlamaReader,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if process.poll() is not None:
            logger.error("llama-server exited during load")
            raise ModelLoadError("llama-server exited during load")
        if reader.healthy():
            return
        if time.monotonic() >= deadline:
            logger.error("llama-server did not become healthy")
            raise ModelLoadError("llama-server did not become healthy")
        time.sleep(0.5)


def _data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _completion(body: object) -> tuple[str, float | None]:
    if not isinstance(body, dict):
        raise RuntimeError("llama-server request failed")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("llama-server request failed")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("llama-server request failed")
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    logprobs = choices[0].get("logprobs")
    tokens: object = None
    if isinstance(logprobs, dict):
        tokens = logprobs.get("content")
    return text, mean_token_probability(tokens)
