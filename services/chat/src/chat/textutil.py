import os
import re
from datetime import UTC, datetime
from pathlib import Path

from tokenizers import Tokenizer

DEFAULT_TITLE = "Новый чат"
NOT_FOUND = "Не найдено в документах."
QUERY_PREFIX = "task: question answering | query: "
# ggml-org/embeddinggemma-2-GGUF .src_sha PRIMARY. Same revision the processor bakes.
TOKENIZER_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
_VENDORED_TOKENIZER = Path(__file__).resolve().parents[2] / "tokenizer" / "tokenizer.json"
_BAKED_TOKENIZER = Path("/app/tokenizer/tokenizer.json")
_TOKENIZER: Tokenizer | None = None

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_WHITESPACE_RE = re.compile(r"\s+")


def canonical_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not _UUID_RE.fullmatch(stripped):
        return None
    return stripped.lower()


def format_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    millis = value.microsecond // 1000
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def title_from_question(content: str) -> str:
    collapsed = _WHITESPACE_RE.sub(" ", content).strip()
    if len(collapsed) <= 80:
        return collapsed
    return collapsed[:77] + "..."


def snippet(text: str) -> str:
    if len(text) <= 500:
        return text
    return text[:497] + "..."


def resolve_tokenizer_file() -> Path:
    """Local ``tokenizer.json`` for revision ``TOKENIZER_REVISION``.

    Order matches the processor: ``TOKENIZER_JSON``, the image path
    ``/app/tokenizer/tokenizer.json``, then the file vendored next to this
    service. Nothing here downloads weights.
    """
    override = os.environ.get("TOKENIZER_JSON")
    if override:
        path = Path(override)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    if _BAKED_TOKENIZER.is_file():
        return _BAKED_TOKENIZER
    if _VENDORED_TOKENIZER.is_file():
        return _VENDORED_TOKENIZER
    raise FileNotFoundError(
        "tokenizer.json for google/embeddinggemma-2 revision " + TOKENIZER_REVISION
    )


def _load_tokenizer() -> Tokenizer:
    global _TOKENIZER
    if _TOKENIZER is None:
        _TOKENIZER = Tokenizer.from_file(str(resolve_tokenizer_file()))
    return _TOKENIZER


def estimate_tokens(text: str) -> int:
    """Token count from EmbeddingGemma ``tokenizer.json``, including ``<bos>`` and ``<eos>``.

    This is the count the embedding service uses. Query truncation must pass the
    prefix and the question as one string: the boundary is not the sum of the
    two counts.
    """
    return len(_load_tokenizer().encode(text, add_special_tokens=True).ids)


def truncate_query(question: str, max_tokens: int) -> str:
    """Cut the question tail so ``prefix + question`` fits ``max_tokens``.

    The prefix ``task: question answering | query: `` is part of the counted
    string. The original question is still what the LLM sees.
    """
    if max_tokens < 1:
        max_tokens = 1
    if estimate_tokens(QUERY_PREFIX + question) <= max_tokens:
        return question
    low = 1
    high = len(question)
    best = question[:1]
    while low <= high:
        mid = (low + high) // 2
        candidate = question[:mid]
        if estimate_tokens(QUERY_PREFIX + candidate) <= max_tokens:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best
