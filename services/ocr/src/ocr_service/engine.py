"""PaddleOCR PP-OCRv4 for English and Russian.

`OCR_MODEL=paddleocr_multilingual` loads two PP-OCRv4 pipelines at process start:

* `lang=en` uses the English PP-OCRv4 recognizer (`en_PP-OCRv4_rec`)
* `lang=ru` is the Cyrillic PP-OCRv4 pipeline (`cyrillic_PP-OCRv3_rec` under
  the PP-OCRv4 multilingual configuration; Paddle publishes no separate
  PP-OCRv4 Cyrillic recognition weights)

Detection weights follow the same version: English `en_PP-OCRv3_det` and
multilingual `Multilingual_PP-OCRv3_det`. The angle classifier is
`ch_ppocr_mobile_v2.0_cls`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

logger = logging.getLogger("ocr")

PADDLE_OCR_VERSION = "PP-OCRv4"
PADDLE_LANGS = ("en", "ru")
# PaddleOCR 2.10 defaults this argument to 10 and passes it to
# set_cpu_math_library_num_threads. Bare Paddle Inference defaults to 1.
# OMP_NUM_THREADS does not replace that call. One process uses one core.
CPU_MATH_THREADS = 1


def pin_native_thread_pools() -> None:
    """Size OpenMP, MKL, and OpenBLAS to one thread before Paddle loads.

    The math-library call inside predictor setup is thread-local. Inference
    runs on the worker that built the predictor; any other thread falls
    back to these variables, or to the host CPU count when they are unset.
    """
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> tuple[str, float | None]:
        """Return recognized text and a score in [0, 1], or None when there is no score."""


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    score: float
    x1: float
    y1: float
    x2: float
    y2: float


class PaddleMultilingualEngine:
    """Real PP-OCRv4 engine. Construction downloads and loads the weights."""

    def __init__(self) -> None:
        pin_native_thread_pools()
        from paddleocr import PaddleOCR

        logger.info(
            "loading OCR model paddleocr_multilingual (PP-OCRv4, en and ru, cpu_threads=%s)",
            CPU_MATH_THREADS,
        )
        self._pipelines = {
            lang: PaddleOCR(
                lang=lang,
                ocr_version=PADDLE_OCR_VERSION,
                use_angle_cls=True,
                use_gpu=False,
                show_log=False,
                cpu_threads=CPU_MATH_THREADS,
                enable_mkldnn=False,
            )
            for lang in PADDLE_LANGS
        }
        logger.info("OCR model paddleocr_multilingual is loaded")

    def recognize(self, image: Image.Image) -> tuple[str, float | None]:
        array = _bgr(image)
        lines: list[_Line] = []
        for lang in PADDLE_LANGS:
            raw = self._pipelines[lang].ocr(array, cls=True)
            lines.extend(_parse_result(raw))
        merged = _merge(lines)
        if not merged:
            return "", None
        text = "\n".join(line.text for line in merged)
        confidence = sum(line.score for line in merged) / len(merged)
        return text, confidence


def _bgr(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _parse_result(result: object) -> list[_Line]:
    if result is None:
        return []
    if not isinstance(result, list):
        raise RuntimeError("unexpected OCR result type")
    if not result:
        return []
    page = result[0]
    if page is None:
        return []
    if not isinstance(page, list):
        raise RuntimeError("unexpected OCR page type")
    lines: list[_Line] = []
    for item in page:
        if item is None:
            continue
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise RuntimeError("unexpected OCR line")
        box, rec = item[0], item[1]
        if not isinstance(rec, (list, tuple)) or len(rec) < 2:
            raise RuntimeError("unexpected OCR line")
        text = str(rec[0]).strip()
        if text == "":
            continue
        try:
            score = float(rec[1])
        except (TypeError, ValueError):
            raise RuntimeError("unexpected OCR score") from None
        if score != score or score in (float("inf"), float("-inf")):
            raise RuntimeError("unexpected OCR score")
        bounds = _bounds(box)
        lines.append(_Line(text, score, *bounds))
    return lines


def _bounds(box: object) -> tuple[float, float, float, float]:
    if not isinstance(box, (list, tuple)) or not box:
        raise RuntimeError("unexpected OCR box")
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    except (TypeError, ValueError, IndexError):
        raise RuntimeError("unexpected OCR box") from None
    return min(xs), min(ys), max(xs), max(ys)


def _merge(lines: list[_Line]) -> list[_Line]:
    """Keep the higher-scoring reading when English and Russian boxes overlap."""
    if not lines:
        return []
    kept: list[_Line] = []
    for line in lines:
        match_at = None
        match_iou = 0.0
        for index, existing in enumerate(kept):
            overlap = _iou(line, existing)
            if overlap > match_iou:
                match_iou = overlap
                match_at = index
        if match_at is not None and match_iou >= 0.3:
            current = kept[match_at]
            if _prefer(line, current):
                kept[match_at] = line
            continue
        kept.append(line)
    kept.sort(key=lambda item: (item.y1, item.x1))
    return kept


def _prefer(candidate: _Line, current: _Line) -> bool:
    if candidate.score > current.score:
        return True
    if candidate.score < current.score:
        return False
    return len(candidate.text) > len(current.text)


def _iou(left: _Line, right: _Line) -> float:
    ix1 = max(left.x1, right.x1)
    iy1 = max(left.y1, right.y1)
    ix2 = min(left.x2, right.x2)
    iy2 = min(left.y2, right.y2)
    width = ix2 - ix1
    height = iy2 - iy1
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    area_left = max(0.0, left.x2 - left.x1) * max(0.0, left.y2 - left.y1)
    area_right = max(0.0, right.x2 - right.x1) * max(0.0, right.y2 - right.y1)
    union = area_left + area_right - intersection
    if union <= 0:
        return 0.0
    return intersection / union
