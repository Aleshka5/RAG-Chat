"""Production engine wiring. PaddleOCR is replaced in-process and is not downloaded."""

from __future__ import annotations

import io
import sys
import types

import pytest
from PIL import Image

from ocr_service.engine import (
    PADDLE_LANGS,
    PADDLE_OCR_VERSION,
    PaddleMultilingualEngine,
)
from ocr_service.main import main


class _RecordingPaddle:
    instances: list[_RecordingPaddle] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.lang = kwargs["lang"]
        _RecordingPaddle.instances.append(self)

    def ocr(self, image: object, cls: bool = True) -> list:
        assert cls is True
        assert getattr(image, "ndim", None) == 3
        if self.lang == "en":
            return [
                [
                    [[[0, 0], [40, 0], [40, 10], [0, 10]], ("Hello", 0.80)],
                    [[[0, 0], [40, 0], [40, 10], [0, 10]], ("dropped", 0.10)],
                ]
            ]
        return [
            [
                [[[0, 0], [40, 0], [40, 10], [0, 10]], ("Хелло", 0.20)],
                [[[2, 30], [50, 30], [50, 48], [2, 48]], ("Привет", 0.91)],
            ]
        ]


def _install_fake_paddle(monkeypatch: pytest.MonkeyPatch) -> None:
    _RecordingPaddle.instances = []
    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _RecordingPaddle  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", module)


def _image() -> Image.Image:
    return Image.new("RGB", (8, 8), "white")


def test_production_engine_constructs_ppocrv4_en_and_ru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_paddle(monkeypatch)
    engine = PaddleMultilingualEngine()
    constructed = _RecordingPaddle.instances
    assert [item.lang for item in constructed] == list(PADDLE_LANGS)
    assert {item.kwargs["ocr_version"] for item in constructed} == {PADDLE_OCR_VERSION}
    assert all(item.kwargs["use_gpu"] is False for item in constructed)
    assert all(item.kwargs["use_angle_cls"] is True for item in constructed)

    text, confidence = engine.recognize(_image())
    assert text == "Hello\nПривет"
    assert confidence == pytest.approx((0.80 + 0.91) / 2)


def test_empty_recognition_is_empty_text_and_null_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Empty:
        def __init__(self, **kwargs: object) -> None:
            pass

        def ocr(self, image: object, cls: bool = True) -> list:
            return [None]

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _Empty  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    engine = PaddleMultilingualEngine()
    text, confidence = engine.recognize(_image())
    assert text == ""
    assert confidence is None


def test_main_loads_real_engine_before_binding_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_paddle(monkeypatch)
    for name in ("OCR_PORT", "OCR_MODEL", "OCR_TIMEOUT", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    started: dict[str, object] = {}

    def _run(app: object, **kwargs: object) -> None:
        started["app"] = app
        started["kwargs"] = kwargs

    monkeypatch.setattr("ocr_service.main.uvicorn.run", _run)
    main()
    app = started["app"]
    kwargs = started["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8090
    assert isinstance(app.state.engine, PaddleMultilingualEngine)
    assert app.state.settings.ocr_model == "paddleocr_multilingual"
    assert app.state.settings.ocr_port == 8090
    assert [item.kwargs["lang"] for item in _RecordingPaddle.instances] == ["en", "ru"]
    assert {item.kwargs["ocr_version"] for item in _RecordingPaddle.instances} == {"PP-OCRv4"}


def test_main_exits_when_model_load_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("weights unavailable")

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _Broken  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    monkeypatch.setattr("ocr_service.main.uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_png_round_trip_bytes() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "black").save(buffer, format="PNG")
    assert buffer.getvalue().startswith(b"\x89PNG")
