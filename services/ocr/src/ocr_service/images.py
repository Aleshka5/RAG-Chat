"""Decode a single raster page. PDF rendering stays in Processor."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError


def decode_raster(data: bytes) -> Image.Image | None:
    """Return an RGB image, or None when the body is not a decodable raster."""
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format == "PDF":
                return None
            image.load()
            if image.width < 1 or image.height < 1:
                return None
            rgb = image.convert("RGB")
            rgb.load()
            return rgb
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
