"""Surya OCR 2 through llama.cpp.

The prompt and the image fit are the training-time contract from Surya.
One multilingual model reads the page. English and Russian are not separate
passes and are not merged by box score.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

from bs4 import BeautifulSoup
from PIL import Image

# Verbatim. Surya trains on this sentence; a paraphrase changes the output.
PAGE_PROMPT = (
    "OCR this image to HTML. Each block is a div with data-label and data-bbox "
    "(x0 y0 x1 y1, normalized 0-1000)."
)
MAX_NEW_TOKENS = 24576
# Image patches plus a full-page completion. Smaller than this truncates the page.
PAGE_CONTEXT = 65536
IMAGE_MIN_TOKENS = 1024

SKIP_LABELS = frozenset({"Figure", "Image", "Diagram", "Blank-Page"})

_FENCE_START = re.compile(r"^```[a-zA-Z]*\n")
_FENCE_END = re.compile(r"\n```\s*$")


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> tuple[str, float | None]:
        """Return recognized text and a score in [0, 1], or None when there is no score."""


class PageReader(Protocol):
    def complete(
        self,
        image: Image.Image,
        prompt: str,
        *,
        temperature: float,
        top_p: float,
    ) -> tuple[str, float | None]:
        """Return the raw completion and the mean token probability."""


class SuryaEngine:
    """Full-page OCR. Weights live in llama-server, not in this process."""

    def __init__(self, reader: PageReader) -> None:
        self._reader = reader

    def recognize(self, image: Image.Image) -> tuple[str, float | None]:
        begin = getattr(self._reader, "begin_page", None)
        if begin is not None:
            begin()
        fitted = scale_to_fit(image)
        raw, confidence = self._reader.complete(
            fitted,
            PAGE_PROMPT,
            temperature=0.0,
            top_p=0.1,
        )
        if repeats(raw):
            try:
                retried, retried_confidence = self._reader.complete(
                    fitted,
                    PAGE_PROMPT,
                    temperature=0.2,
                    top_p=0.95,
                )
            except TimeoutError:
                raw, confidence = cut_repeated_tail(raw), confidence
            else:
                if repeats(retried):
                    first = cut_repeated_tail(raw)
                    second = cut_repeated_tail(retried)
                    if len(second) > len(first):
                        raw, confidence = second, retried_confidence
                    else:
                        raw, confidence = first, confidence
                else:
                    raw, confidence = retried, retried_confidence
        return page_text(raw), confidence

    def close(self) -> None:
        close = getattr(self._reader, "close", None)
        if close is not None:
            close()


def scale_to_fit(
    img: Image.Image,
    max_size: tuple[int, int] = (3072, 2048),
    min_size: tuple[int, int] = (1792, 28),
    grid_size: int = 28,
) -> Image.Image:
    """Match Surya's image fit: pixel budget, then a multiple of the vision grid."""
    width, height = img.size
    if width <= 0 or height <= 0:
        return img
    original_ar = width / height
    current_pixels = width * height
    max_pixels = max_size[0] * max_size[1]
    min_pixels = min_size[0] * min_size[1]
    scale = 1.0
    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
    elif current_pixels < min_pixels:
        scale = (min_pixels / current_pixels) ** 0.5
    w_blocks = max(1, round((width * scale) / grid_size))
    h_blocks = max(1, round((height * scale) / grid_size))
    while (w_blocks * h_blocks * grid_size * grid_size) > max_pixels:
        if w_blocks == 1 and h_blocks == 1:
            break
        if w_blocks == 1:
            h_blocks -= 1
            continue
        if h_blocks == 1:
            w_blocks -= 1
            continue
        ar_w_loss = abs(((w_blocks - 1) / h_blocks) - original_ar)
        ar_h_loss = abs((w_blocks / (h_blocks - 1)) - original_ar)
        if ar_w_loss < ar_h_loss:
            w_blocks -= 1
        else:
            h_blocks -= 1
    new_width = w_blocks * grid_size
    new_height = h_blocks * grid_size
    if (new_width, new_height) == (width, height):
        return img
    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def page_text(raw: str) -> str:
    """Plain text in the order Surya emitted the blocks."""
    cleaned = _drop_thinking(_strip_fences(raw)).strip()
    if not cleaned:
        return ""
    soup = BeautifulSoup(cleaned, "html.parser")
    blocks: list[str] = []
    for div in soup.find_all("div", recursive=False):
        label = str(div.get("data-label") or "")
        if label in SKIP_LABELS:
            continue
        text = div.get_text("\n", strip=True)
        if text:
            blocks.append(text)
    if blocks:
        return "\n".join(blocks)
    return soup.get_text("\n", strip=True)


def repeats(text: str) -> bool:
    """True when the tail of the completion is the same short span many times."""
    return _repeat_start(text) is not None or (
        len(text) > 50 and _repeat_start(text[:-50]) is not None
    )


def cut_repeated_tail(text: str) -> str:
    """Drop a repeating tail so the page keeps the text that came before the loop."""
    starts: list[int] = []
    start = _repeat_start(text)
    if start is not None:
        starts.append(start)
    if len(text) > 50:
        earlier = _repeat_start(text[:-50])
        if earlier is not None:
            starts.append(earlier)
    if not starts:
        return text
    return text[: min(starts)]


def _repeat_start(
    text: str,
    base_max_repeats: int = 4,
    window_size: int = 500,
) -> int | None:
    """Index where a repeating tail begins, or None when the tail is not a loop."""
    if not text:
        return None
    limit = min(window_size // 2, len(text))
    for seq_len in range(1, limit + 1):
        candidate = text[-seq_len:]
        max_repeats = int(base_max_repeats * (1 + 3.0 / seq_len))
        count = 0
        pos = len(text) - seq_len
        while pos >= 0 and text[pos : pos + seq_len] == candidate:
            count += 1
            pos -= seq_len
        if count > max_repeats:
            return pos + seq_len
    return None


def mean_token_probability(logprobs: object) -> float | None:
    if not isinstance(logprobs, list) or not logprobs:
        return None
    probs: list[float] = []
    for item in logprobs:
        if not isinstance(item, dict):
            continue
        value = item.get("logprob")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(float(value)):
            continue
        probs.append(math.exp(float(value)))
    if not probs:
        return None
    return sum(probs) / len(probs)


def _drop_thinking(text: str) -> str:
    """Qwen3.5 writes a reasoning trace before the page when thinking is left on."""
    if "<think>" not in text:
        return text
    closed = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "<think>" in closed:
        return closed.split("<think>", 1)[0]
    return closed


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_START.sub("", cleaned)
        cleaned = _FENCE_END.sub("", cleaned)
    return cleaned
