from dataclasses import dataclass
from typing import Literal

from embedding.config import Settings
from embedding.errors import ValidationFailed
from embedding.images import DecodedImage, decode_images
from embedding.prefixes import prefix_document, prefix_query

_MISSING = object()
InputType = Literal["document", "query"]
# Fields of the text contract. Mixing them into an image request is a mistake,
# not a preference: an image takes no prefix, and silently ignoring the text
# would return a vector of something else.
_TEXT_FIELDS = ("texts", "input_type", "title")


@dataclass(frozen=True)
class ParsedEmbed:
    texts: list[str]
    input_type: InputType
    title: str | None
    prefixed: list[str]


@dataclass(frozen=True)
class ParsedImageEmbed:
    images: list[DecodedImage]


def parse_embed_request(payload: object, settings: Settings) -> ParsedEmbed:
    body = _as_object(payload)

    raw_type = body.get("input_type", _MISSING)
    if raw_type is _MISSING:
        raise ValidationFailed("input_type is required", ["input_type"])
    if raw_type not in {"document", "query"}:
        raise ValidationFailed("input_type must be document or query", ["input_type"])
    input_type: InputType = "document" if raw_type == "document" else "query"

    title: str | None = None
    if input_type == "query":
        if "title" in body:
            raise ValidationFailed("title is not allowed when input_type is query", ["title"])
    else:
        if "title" not in body or not isinstance(body["title"], str):
            raise ValidationFailed("title is required when input_type is document", ["title"])
        title = body["title"].strip()
        if title == "":
            raise ValidationFailed("title is required when input_type is document", ["title"])

    _check_model(body, settings)

    if "texts" not in body:
        raise ValidationFailed("texts is required", ["texts"])
    texts = body["texts"]
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


def parse_image_request(payload: object, settings: Settings) -> ParsedImageEmbed:
    """One vector per image, no prefix: images are passed to the model bare."""
    body = _as_object(payload)

    stray = [field for field in _TEXT_FIELDS if field in body]
    if stray:
        raise ValidationFailed(
            f"{', '.join(stray)} is not accepted on /embed/image",
            stray,
        )

    _check_model(body, settings)

    if "images" not in body:
        raise ValidationFailed("images is required", ["images"])
    return ParsedImageEmbed(
        images=decode_images(
            body["images"],
            max_images=settings.max_images,
            max_bytes=settings.max_image_bytes,
        )
    )


def _as_object(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValidationFailed("Request body must be a JSON object", ["body"])
    return payload


def _check_model(body: dict[str, object], settings: Settings) -> None:
    if "model" in body:
        model = body["model"]
        if not isinstance(model, str) or model != settings.model:
            raise ValidationFailed("model must match EMBEDDING_MODEL", ["model"])
