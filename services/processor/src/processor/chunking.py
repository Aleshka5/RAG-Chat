from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from processor.errors import ConfigError


class TextTokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, token_ids: list[int]) -> str: ...


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    origin: str
    unit_label: str | None = None


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    page_number: int
    page_end: int
    source: str
    unit_label: str | None = None


def build_chunks(
    pages: list[PageText],
    tokenizer: TextTokenizer,
    *,
    size: int,
    overlap: int,
) -> list[Chunk]:
    """Sliding token window from processing.md.

    Content tokens only: the embedding service adds the ``title`` / ``text``
    prefix, and special tokens are applied when that prefixed string is encoded.
    Page token lists are concatenated in page order. ``origin=empty`` pages
    contribute nothing. A window whose decoded text is empty after ``strip``
    does not become a chunk, and ``chunk_index`` stays dense. ``unit_label``
    is taken from the window's first token.
    """
    if overlap >= size:
        raise ConfigError("CHUNK_OVERLAP_TOKENS")
    tokens: list[tuple[int, int, str, str | None]] = []
    for page in pages:
        if page.origin == "empty" or page.text.strip() == "":
            continue
        for token_id in tokenizer.encode(page.text):
            tokens.append((token_id, page.page_number, page.origin, page.unit_label))
    if not tokens:
        return []

    chunks: list[Chunk] = []
    start = 0
    total = len(tokens)
    while True:
        end = min(start + size, total)
        window = tokens[start:end]
        text = tokenizer.decode([item[0] for item in window])
        if text.strip():
            source = "ocr" if any(item[2] == "ocr" for item in window) else "text"
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=text,
                    page_number=window[0][1],
                    page_end=window[-1][1],
                    source=source,
                    unit_label=window[0][3],
                )
            )
        if end >= total:
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start
    return chunks
