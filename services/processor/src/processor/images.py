from __future__ import annotations

# 10 MiB. Larger objects are a permanent failure and are not sent to the embedder.
MAX_IMAGE_BYTES = 10485760

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_GIF_VERSIONS = (b"GIF87a", b"GIF89a")


class UndecodableImage(Exception):
    """The object bytes are not a decodable image of the declared type."""


def exceeds_image_limit(data: bytes) -> bool:
    return len(data) > MAX_IMAGE_BYTES


def ensure_decodable_image(data: bytes, content_type: str) -> None:
    if content_type == "image/jpeg":
        _require_jpeg(data)
        return
    if content_type == "image/png":
        _require_png(data)
        return
    if content_type == "image/gif":
        _require_gif(data)
        return
    if content_type == "image/webp":
        _require_webp(data)
        return
    raise UndecodableImage(content_type)


def _require_jpeg(data: bytes) -> None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise UndecodableImage("jpeg")
    index = 2
    saw_frame = False
    saw_scan = False
    while index < len(data):
        if data[index] != 0xFF:
            raise UndecodableImage("jpeg")
        index += 1
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            raise UndecodableImage("jpeg")
        marker = data[index]
        index += 1
        if marker == 0xD8:
            continue
        if marker == 0xD9:
            if not saw_frame or not saw_scan:
                raise UndecodableImage("jpeg")
            return
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            raise UndecodableImage("jpeg")
        length = int.from_bytes(data[index : index + 2], "big")
        if length < 2 or index + length > len(data):
            raise UndecodableImage("jpeg")
        if marker in _JPEG_SOF:
            if length < 7:
                raise UndecodableImage("jpeg")
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            if width < 1 or height < 1:
                raise UndecodableImage("jpeg")
            saw_frame = True
        if marker == 0xDA:
            if not saw_frame:
                raise UndecodableImage("jpeg")
            saw_scan = True
            index += length
            index = _jpeg_scan_end(data, index)
            continue
        index += length
    raise UndecodableImage("jpeg")


def _jpeg_scan_end(data: bytes, index: int) -> int:
    """Return the index of the next marker after an entropy-coded scan."""
    while index + 1 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xFF:
            index += 1
            continue
        return index
    raise UndecodableImage("jpeg")


def _require_png(data: bytes) -> None:
    if not data.startswith(_PNG_SIGNATURE):
        raise UndecodableImage("png")
    offset = len(_PNG_SIGNATURE)
    saw_header = False
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        if offset + length + 4 > len(data):
            raise UndecodableImage("png")
        chunk = data[offset : offset + length]
        offset += length + 4
        if chunk_type == b"IHDR":
            if saw_header or length < 13:
                raise UndecodableImage("png")
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            if width < 1 or height < 1:
                raise UndecodableImage("png")
            saw_header = True
            continue
        if not saw_header:
            raise UndecodableImage("png")
        if chunk_type == b"IEND":
            return
    raise UndecodableImage("png")


def _require_gif(data: bytes) -> None:
    if len(data) < 13 or data[:6] not in _GIF_VERSIONS:
        raise UndecodableImage("gif")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    if width < 1 or height < 1:
        raise UndecodableImage("gif")
    packed = data[10]
    offset = 13
    if packed & 0x80:
        offset += 3 * (2 ** ((packed & 0x07) + 1))
    if offset > len(data):
        raise UndecodableImage("gif")
    saw_image = False
    while offset < len(data):
        block = data[offset]
        if block == 0x3B:
            if not saw_image:
                raise UndecodableImage("gif")
            return
        if block == 0x21:
            if offset + 2 > len(data):
                raise UndecodableImage("gif")
            offset = _gif_subblocks(data, offset + 2)
            continue
        if block == 0x2C:
            if offset + 10 > len(data):
                raise UndecodableImage("gif")
            image_width = int.from_bytes(data[offset + 5 : offset + 7], "little")
            image_height = int.from_bytes(data[offset + 7 : offset + 9], "little")
            if image_width < 1 or image_height < 1:
                raise UndecodableImage("gif")
            local = data[offset + 9]
            offset += 10
            if local & 0x80:
                offset += 3 * (2 ** ((local & 0x07) + 1))
            if offset >= len(data):
                raise UndecodableImage("gif")
            offset += 1
            offset = _gif_subblocks(data, offset)
            saw_image = True
            continue
        raise UndecodableImage("gif")
    raise UndecodableImage("gif")


def _gif_subblocks(data: bytes, offset: int) -> int:
    while offset < len(data):
        size = data[offset]
        offset += 1
        if size == 0:
            return offset
        if offset + size > len(data):
            raise UndecodableImage("gif")
        offset += size
    raise UndecodableImage("gif")


def _require_webp(data: bytes) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise UndecodableImage("webp")
    riff_size = int.from_bytes(data[4:8], "little")
    if riff_size + 8 != len(data) or riff_size < 4:
        raise UndecodableImage("webp")
    offset = 12
    saw_bitmap = False
    while offset + 8 <= len(data):
        tag = data[offset : offset + 4]
        size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        offset += 8
        padded = size + (size & 1)
        if size < 0 or offset + padded > len(data):
            # The last chunk may omit the pad byte when it would run past the file.
            if size < 0 or offset + size > len(data):
                raise UndecodableImage("webp")
            padded = size
        chunk = data[offset : offset + size]
        offset += padded
        if tag == b"VP8 ":
            _vp8_size(chunk)
            saw_bitmap = True
        elif tag == b"VP8L":
            _vp8l_size(chunk)
            saw_bitmap = True
        elif tag == b"VP8X":
            _vp8x_size(chunk)
    if not saw_bitmap or offset != len(data):
        raise UndecodableImage("webp")


def _vp8_size(chunk: bytes) -> None:
    if len(chunk) < 10 or chunk[0] & 0x01 != 0 or chunk[3:6] != b"\x9d\x01\x2a":
        raise UndecodableImage("webp")
    width = int.from_bytes(chunk[6:8], "little") & 0x3FFF
    height = int.from_bytes(chunk[8:10], "little") & 0x3FFF
    if width < 1 or height < 1:
        raise UndecodableImage("webp")


def _vp8l_size(chunk: bytes) -> None:
    if len(chunk) < 5 or chunk[0] != 0x2F:
        raise UndecodableImage("webp")
    bits = int.from_bytes(chunk[1:5], "little")
    width = (bits & 0x3FFF) + 1
    height = ((bits >> 14) & 0x3FFF) + 1
    if width < 1 or height < 1:
        raise UndecodableImage("webp")


def _vp8x_size(chunk: bytes) -> None:
    if len(chunk) < 10:
        raise UndecodableImage("webp")
    width = 1 + int.from_bytes(chunk[4:7], "little")
    height = 1 + int.from_bytes(chunk[7:10], "little")
    if width < 1 or height < 1:
        raise UndecodableImage("webp")
