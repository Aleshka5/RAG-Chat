"""Prompt prefixes from the EmbeddingGemma 2 question-answering card.

Spaces and separators are significant. The prefix is visible only to the
embedding model; callers store and prompt with the original text.
"""


def prefix_query(text: str) -> str:
    return f"task: question answering | query: {text}"


def prefix_document(title: str, text: str) -> str:
    return f"title: {title} | text: {text}"
