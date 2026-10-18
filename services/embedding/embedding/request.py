from dataclasses import dataclass
from typing import Literal

from embedding.config import Settings
from embedding.errors import ValidationFailed
from embedding.prefixes import prefix_document, prefix_query

_MISSING = object()
InputType = Literal["document", "query"]


@dataclass(frozen=True)
class ParsedEmbed:
    texts: list[str]
    input_type: InputType
    title: str | None
    prefixed: list[str]


def parse_embed_request(payload: object, settings: Settings) -> ParsedEmbed:
    if not isinstance(payload, dict):
        raise ValidationFailed("Request body must be a JSON object", ["body"])

    input_type = payload.get("input_type", _MISSING)
    if input_type is _MISSING:
        raise ValidationFailed("input_type is required", ["input_type"])
    if input_type not in {"document", "query"}:
        raise ValidationFailed("input_type must be document or query", ["input_type"])

    title: str | None = None
    if input_type == "query":
        if "title" in payload:
            raise ValidationFailed("title is not allowed when input_type is query", ["title"])
    else:
        if "title" not in payload or not isinstance(payload["title"], str):
            raise ValidationFailed("title is required when input_type is document", ["title"])
        title = payload["title"].strip()
        if title == "":
            raise ValidationFailed("title is required when input_type is document", ["title"])

    if "model" in payload:
        model = payload["model"]
        if not isinstance(model, str) or model != settings.model:
            raise ValidationFailed("model must match EMBEDDING_MODEL", ["model"])

    if "texts" not in payload:
        raise ValidationFailed("texts is required", ["texts"])
    texts = payload["texts"]
    if not isinstance(texts, list):
        raise ValidationFailed("texts must be an array of strings", ["texts"])
    if not 1 <= len(texts) <= settings.batch_size:
        raise ValidationFailed(
            f"texts must contain between 1 and {settings.batch_size} items",
            ["texts"],
        )

    cleaned: list[str] = []
    for item in texts:
        if not isinstance(item, str):
            raise ValidationFailed("texts must be non-empty strings", ["texts"])
        stripped = item.strip()
        if stripped == "":
            raise ValidationFailed("texts must be non-empty strings", ["texts"])
        cleaned.append(stripped)

    if input_type == "document":
        assert title is not None
        prefixed = [prefix_document(title, text) for text in cleaned]
    else:
        prefixed = [prefix_query(text) for text in cleaned]
    return ParsedEmbed(
        texts=cleaned,
        input_type=input_type,
        title=title,
        prefixed=prefixed,
    )
