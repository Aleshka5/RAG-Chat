import re
from datetime import UTC, datetime

DEFAULT_TITLE = "Новый чат"
NOT_FOUND = "Не найдено в документах."
QUERY_PREFIX = "task: question answering | query: "

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


def estimate_tokens(text: str) -> int:
    """Conservative token estimate so a question plus the query prefix fits the embedder.

    EmbeddingGemma's tokenizer is not bundled. Two characters per token over-counts
    English and is close to Cyrillic, which keeps the embed request under the limit.
    The original question is still what the LLM sees.
    """
    if not text:
        return 0
    return (len(text) + 1) // 2


def truncate_query(question: str, max_tokens: int) -> str:
    budget = max_tokens - estimate_tokens(QUERY_PREFIX)
    if budget < 1:
        budget = 1
    if estimate_tokens(question) <= budget:
        return question
    low = 1
    high = len(question)
    best = question[:1]
    while low <= high:
        mid = (low + high) // 2
        if estimate_tokens(question[:mid]) <= budget:
            best = question[:mid]
            low = mid + 1
        else:
            high = mid - 1
    return best
