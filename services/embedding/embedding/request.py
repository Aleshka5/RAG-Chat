import base64
import binascii
from dataclasses import dataclass
from typing import Literal

from embedding.config import Settings
from embedding.encoder import ImageInput
from embedding.errors import ValidationFailed
from embedding.prefixes import prefix_document, prefix_query

_MISSING = object()
InputType = Literal["document", "query"]
_TEXT_FIELDS = ("texts", "input_type", "title")
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF = (b"GIF87a", b"GIF89a")
_RIFF = b"RIFF"
_WEBP = b"WEBP"


@dataclass(frozen=True)
class ParsedEmbed:
    texts: list[str]
    input_type: InputType
    title: str | None
    prefixed: list[str]


@dataclass(frozen=True)
class ParsedImageEmbed:
    images: list[ImageInput]


def parse_embed_request(payload: object, settings: Settings) -> ParsedEmbed:
    payload = _object_payload(payload)

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

    _check_model(payload, settings)

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


def parse_image_embed_request(payload: object, settings: Settings) -> ParsedImageEmbed:
    payload = _object_payload(payload)
    _reject_image_fields(payload)
    _check_model(payload, settings)

    if "images" not in payload:
        raise ValidationFailed("images is required", ["images"])
    images = payload["images"]
    if not isinstance(images, list):
        raise ValidationFailed("images must be an array of base64 strings", ["images"])
    if not 1 <= len(images) <= settings.max_images:
        raise ValidationFailed(
            f"images must contain between 1 and {settings.max_images} items",
            ["images"],
        )

    parsed: list[ImageInput] = []
    for item in images:
        parsed.append(_parse_image(item, settings.max_image_bytes))
    return ParsedImageEmbed(images=parsed)


def sniff_media_type(data: bytes) -> str:
    """Container from magic bytes. JPEG, PNG, GIF87a/GIF89a, or WebP."""
    if data.startswith(_JPEG):
        return "image/jpeg"
    if data.startswith(_PNG):
        return "image/png"
    if data.startswith(_GIF):
        return "image/gif"
    if len(data) >= 12 and data[:4] == _RIFF and data[8:12] == _WEBP:
        return "image/webp"
    raise ValidationFailed("unsupported image format", ["images"])


def _object_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValidationFailed("Request body must be a JSON object", ["body"])
    return payload


def _reject_image_fields(payload: dict[str, object]) -> None:
    """Name every text field. The image schema allows only images and model."""
    fields = [name for name in _TEXT_FIELDS if name in payload]
    fields.extend(name for name in payload if name not in {"images", "model", *_TEXT_FIELDS})
    if not fields:
        return
    if len(fields) == 1:
        raise ValidationFailed(f"{fields[0]} is not allowed", fields)
    raise ValidationFailed("Unexpected fields", fields)


def _check_model(payload: dict[str, object], settings: Settings) -> None:
    if "model" not in payload:
        return
    model = payload["model"]
    if not isinstance(model, str) or model != settings.model:
        raise ValidationFailed("model must match EMBEDDING_MODEL", ["model"])


def _parse_image(item: object, max_bytes: int) -> ImageInput:
    if not isinstance(item, str) or item == "":
        raise ValidationFailed("images must be base64-encoded", ["images"])
    try:
        decoded = base64.b64decode(item, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationFailed("images must be base64-encoded", ["images"]) from None
    if len(decoded) > max_bytes:
        raise ValidationFailed("image exceeds EMBEDDING_MAX_IMAGE_BYTES", ["images"])
    return ImageInput(media_type=sniff_media_type(decoded), base64_data=item)
