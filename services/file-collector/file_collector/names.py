"""File name cleanup for file_name and the object key."""

import re
from urllib.parse import quote

_UNSAFE_NAME = re.compile(r"[\x00\r\n]")
_REPEATED_UNDERSCORE = re.compile(r"_+")


def basename(raw: str) -> str:
    name = raw.replace("\\", "/")
    return name.split("/")[-1]


def validated_file_name(raw: str | None) -> str:
    """Return the stored display name, or raise ValueError if it is unusable."""
    if raw is None:
        raise ValueError("file")
    base = basename(raw)
    if base in {"", ".", ".."} or len(base) > 255 or _UNSAFE_NAME.search(base):
        raise ValueError("file")
    return base


def safe_name(original: str, *, pdf_extension: bool = True) -> str:
    """Object-key segment. Unicode letters and digits stay.

    PDF intake forces a ``.pdf`` extension. Manifests that pass
    ``pdf_extension=False`` keep the cleaned extension.
    """
    base = basename(original)
    cleaned: list[str] = []
    for char in base:
        if char.isalpha() or char.isdigit() or char in "._-":
            cleaned.append(char)
        else:
            cleaned.append("_")
    collapsed = _REPEATED_UNDERSCORE.sub("_", "".join(cleaned))[:200]
    if not pdf_extension:
        if collapsed == "":
            return "document"
        return collapsed
    if collapsed == "":
        return "document.pdf"
    named = _force_pdf_extension(collapsed)
    if len(named) > 200:
        named = named[:196] + ".pdf"
    if named in {"", ".pdf"}:
        return "document.pdf"
    return named


def _force_pdf_extension(name: str) -> str:
    if name.lower().endswith(".pdf"):
        return name[:-4] + ".pdf"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{stem}.pdf"


def content_disposition(file_name: str) -> str:
    ascii_fallback = []
    for char in file_name:
        code = ord(char)
        if 0x20 <= code < 0x7F and char not in {'"', "\\"}:
            ascii_fallback.append(char)
        else:
            ascii_fallback.append("_")
    fallback = "".join(ascii_fallback) or "document.pdf"
    encoded = quote(file_name, safe="")
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
