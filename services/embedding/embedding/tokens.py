from pathlib import Path
from typing import Protocol

from tokenizers import Tokenizer


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class TokenizerJsonCounter:
    """Count ids from the EmbeddingGemma tokenizer.json, including its template.

    ``tokenizer.json`` wraps one sequence as ``<bos> … <eos>``. ``encode``
    applies that post-processor when ``add_special_tokens`` is true, which is
    the count shared with document chunking and query truncation.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    def count(self, text: str) -> int:
        encoded = self._tokenizer.encode(text, add_special_tokens=True)
        return len(encoded.ids)

    @classmethod
    def from_file(cls, path: Path) -> "TokenizerJsonCounter":
        return cls(Tokenizer.from_file(str(path)))
