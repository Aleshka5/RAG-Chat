"""Decode and check base64 image payloads before they reach llama-server.

The container is sniffed from the bytes: a client-declared content type is not
part of the contract, and llama-server answers an unreadable container with a
500 of its own, which the caller would see as ``upstream_failed``.
"""

import base64
import binascii
from dataclasses import dataclass

from embedding.constants import IMAGE_FORMATS, RIFF_MAGIC, WEBP_MAGIC, WEBP_OFFSET
from embedding.errors import ValidationFailed

ACCEPTED_FORMATS = "PNG, JPEG, WebP or GIF"


@dataclass(frozen=True)
class DecodedImage:
    data: bytes
    format: str


def decode_images(items: object, *, max_images: int, max_bytes: int) -> list[DecodedImage]:
    if not isinstance(items, list):
        raise ValidationFailed("images must be an array of base64 strings", ["images"])
    if not 1 <= len(items) <= max_images:
        raise ValidationFailed(
            f"images must contain between 1 and {max_images} items",
            ["images"],
        )

    decoded: list[DecodedImage] = []
    for item in items:
        if not isinstance(item, str):
            raise ValidationFailed("images must be base64 strings", ["images"])
        stripped = item.strip()
        if stripped == "":
            raise ValidationFailed("images must be non-empty base64 strings", ["images"])
        try:
            data = base64.b64decode(stripped, validate=True)
        except (binascii.Error, ValueError):
            raise ValidationFailed("images must be valid base64", ["images"]) from None
        if not data:
            raise ValidationFailed("images must not be empty", ["images"])
        if len(data) > max_bytes:
            raise ValidationFailed(
                f"each image must be at most {max_bytes} bytes",
                ["images"],
            )
        decoded.append(DecodedImage(data=data, format=detect_format(data)))
    return decoded


def detect_format(data: bytes) -> str:
    for magic, name in IMAGE_FORMATS:
        if data.startswith(magic):
            return name
    if data[:4] == RIFF_MAGIC and data[WEBP_OFFSET : WEBP_OFFSET + 4] == WEBP_MAGIC:
        return "webp"
    raise ValidationFailed(f"images must be {ACCEPTED_FORMATS}", ["images"])
