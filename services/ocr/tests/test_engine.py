"""Surya page decoding. llama-server and the GGUF files are not started."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from PIL import Image

from ocr_service.engine import (
    PAGE_CONTEXT,
    PAGE_PROMPT,
    SuryaEngine,
    cut_repeated_tail,
    mean_token_probability,
    page_text,
    repeats,
    scale_to_fit,
)
from ocr_service.llama import _read_stream, build_llama_server_command
from ocr_service.main import main


class _Reader:
    def __init__(self, raw: str, confidence: float | None = 0.8) -> None:
        self.raw = raw
        self.confidence = confidence
        self.prompts: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.temperatures: list[float] = []
        self.top_ps: list[float] = []

    def complete(
        self,
        image: Image.Image,
        prompt: str,
        *,
        temperature: float,
        top_p: float,
    ) -> tuple[str, float | None]:
        self.prompts.append(prompt)
        self.sizes.append(image.size)
        self.temperatures.append(temperature)
        self.top_ps.append(top_p)
        return self.raw, self.confidence


def test_page_keeps_reading_order_and_skips_figures() -> None:
    raw = """
    <div data-label="Section-Header" data-bbox="0 0 400 40"><h1>Заголовок</h1></div>
    <div data-label="Image" data-bbox="0 40 100 80">not text</div>
    <div data-label="Text" data-bbox="0 80 400 200"><p>Hello</p><p>Привет</p></div>
    """
    assert page_text(raw) == "Заголовок\nHello\nПривет"


def test_fenced_html_and_empty_page() -> None:
    fenced = '```html\n<div data-label="Text" data-bbox="0 0 1 1">Line</div>\n```'
    assert page_text(fenced) == "Line"
    assert page_text("   ") == ""
    assert page_text("<p>plain</p>") == "plain"


def test_recognize_uses_the_training_prompt_and_fitted_image() -> None:
    reader = _Reader('<div data-label="Text" data-bbox="0 0 10 10">Hello</div>')
    engine = SuryaEngine(reader)
    text, confidence = engine.recognize(Image.new("RGB", (8, 8), "white"))
    assert text == "Hello"
    assert confidence == 0.8
    assert reader.prompts == [PAGE_PROMPT]
    assert reader.temperatures == [0.0]
    assert reader.top_ps == [0.1]
    width, height = reader.sizes[0]
    assert width % 28 == 0 and height % 28 == 0
    assert width * height <= 3072 * 2048


def test_repeated_completion_is_sampled_once_more() -> None:
    reader = _Reader("aaaa" * 40)
    SuryaEngine(reader).recognize(Image.new("RGB", (64, 64), "white"))
    assert reader.temperatures == [0.0, 0.2]
    assert reader.top_ps == [0.1, 0.95]


def test_scale_to_fit_shrinks_a_large_page() -> None:
    fitted = scale_to_fit(Image.new("RGB", (4000, 6000), "white"))
    assert fitted.size[0] % 28 == 0
    assert fitted.size[1] % 28 == 0
    assert fitted.size[0] * fitted.size[1] <= 3072 * 2048


def test_repeat_detector_and_token_probability() -> None:
    assert repeats("abc" * 30)
    assert not repeats("Hello Привет")
    assert cut_repeated_tail("Hello" + "ab" * 30) == "Hello"
    assert cut_repeated_tail("Hello Привет") == "Hello Привет"
    assert mean_token_probability([{"logprob": 0.0}, {"logprob": -0.693147}]) == pytest.approx(0.75)
    assert mean_token_probability([]) is None
    assert mean_token_probability([{"logprob": float("nan")}]) is None


def test_thinking_trace_is_not_page_text() -> None:
    raw = (
        "<think>reasoning that must not be indexed</think>"
        '<div data-label="Text" data-bbox="0 0 1 1">Строка</div>'
    )
    assert page_text(raw) == "Строка"
    assert page_text("<think>never closed") == ""


def test_stream_stops_when_the_tail_repeats() -> None:
    chunk = {
        "choices": [
            {
                "delta": {"content": "ab"},
                "logprobs": {"content": [{"logprob": 0.0}]},
            }
        ]
    }
    lines = [f"data: {json.dumps(chunk)}" for _ in range(40)]
    lines.append('data: {"choices":[{"delta":{"content":"TAIL"}}]}')
    lines.append("data: [DONE]")
    text, confidence = _read_stream(lines, time.monotonic() + 30)
    assert "TAIL" not in text
    assert repeats(text)
    assert confidence == 1.0


def test_stream_budget_does_not_return_a_partial_page() -> None:
    lines = ['data: {"choices":[{"delta":{"content":"Hello"}}]}']
    with pytest.raises(TimeoutError):
        _read_stream(lines, time.monotonic() - 1)


def test_llama_command_does_not_cap_threads_or_memory() -> None:
    command = build_llama_server_command(
        binary="llama-server",
        model_path=Path("surya-2.gguf"),
        mmproj_path=Path("surya-2-mmproj.gguf"),
        host="127.0.0.1",
        port=8092,
    )
    flags = set(command)
    assert "--threads" not in flags
    assert "-t" not in flags
    assert "--threads-batch" not in flags
    assert "--parallel" not in flags
    assert "OMP_NUM_THREADS" not in flags
    assert command[command.index("--cache-ram") + 1] == "-1"
    assert command[command.index("--ctx-size") + 1] == str(PAGE_CONTEXT)
    assert command[command.index("--mmproj") + 1].endswith("surya-2-mmproj.gguf")
    assert "--jinja" in flags
    assert "-ngl" in flags
    assert command[command.index("--reasoning") + 1] == "off"


def test_main_loads_engine_before_binding_port(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OCR_PORT", "OCR_MODEL", "OCR_TIMEOUT", "OCR_LLAMA_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    started: dict[str, object] = {}

    class _Ready:
        def complete(
            self,
            image: Image.Image,
            prompt: str,
            *,
            temperature: float,
            top_p: float,
        ) -> tuple[str, float | None]:
            return '<div data-label="Text" data-bbox="0 0 1 1">ok</div>', 0.5

        def close(self) -> None:
            started["closed"] = True

    def _run(app: object, **kwargs: object) -> None:
        started["app"] = app
        started["kwargs"] = kwargs

    monkeypatch.setattr("ocr_service.main.start_reader", lambda settings: _Ready())
    monkeypatch.setattr("ocr_service.main.uvicorn.run", _run)
    main()
    app = started["app"]
    kwargs = started["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8090
    assert isinstance(app.state.engine, SuryaEngine)
    assert app.state.settings.ocr_model == "surya-ocr-2"
    assert app.state.settings.ocr_timeout == 60
    text, confidence = app.state.engine.recognize(Image.new("RGB", (32, 32), "white"))
    assert text == "ok"
    assert confidence == 0.5


def test_main_exits_when_model_load_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(settings: object) -> object:
        raise RuntimeError("weights unavailable")

    monkeypatch.setattr("ocr_service.main.start_reader", _boom)
    monkeypatch.setattr("ocr_service.main.uvicorn.run", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_png_round_trip_bytes() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "black").save(buffer, format="PNG")
    assert buffer.getvalue().startswith(b"\x89PNG")
