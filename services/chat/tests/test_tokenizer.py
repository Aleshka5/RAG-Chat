from pathlib import Path

from tokenizers import Tokenizer

from chat.textutil import (
    QUERY_PREFIX,
    TOKENIZER_REVISION,
    estimate_tokens,
    resolve_tokenizer_file,
    truncate_query,
)

GGUF_TOKENIZER_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"


def _count(tokenizer: Tokenizer, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=True).ids)


def test_long_question_is_truncated_with_the_vendored_tokenizer():
    assert TOKENIZER_REVISION == GGUF_TOKENIZER_REVISION
    path = resolve_tokenizer_file()
    assert path == Path(__file__).resolve().parents[1] / "tokenizer" / "tokenizer.json"
    assert path.is_file()
    assert "huggingface" not in path.parts

    tokenizer = Tokenizer.from_file(str(path))
    question = "я" * 4000
    trimmed = truncate_query(question, 1024)
    assert trimmed != question
    assert trimmed
    assert _count(tokenizer, QUERY_PREFIX + trimmed) <= 1024
    assert _count(tokenizer, QUERY_PREFIX + question[: len(trimmed) + 1]) > 1024
    assert estimate_tokens(QUERY_PREFIX + trimmed) == _count(tokenizer, QUERY_PREFIX + trimmed)


def test_prefix_is_inside_the_token_budget():
    question = "я" * 40
    limit = estimate_tokens(question)
    assert estimate_tokens(question) <= limit
    assert estimate_tokens(QUERY_PREFIX + question) > limit
    trimmed = truncate_query(question, limit)
    assert len(trimmed) < len(question)
    assert estimate_tokens(QUERY_PREFIX + trimmed) <= limit
    assert estimate_tokens(QUERY_PREFIX + question[: len(trimmed) + 1]) > limit
    assert estimate_tokens(QUERY_PREFIX + trimmed) > estimate_tokens(trimmed)
