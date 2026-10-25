import pymupdf
import pytest

from processor.images import MAX_IMAGE_BYTES, UndecodableImage, ensure_decodable_image, exceeds_image_limit

GIF = (
    b"GIF87a\x01\x00\x01\x00\x81\x00\x00\x01\x02\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x08\x04\x00\x01\x04\x04\x00;"
)
WEBP = (
    b"RIFF$\x00\x00\x00WEBPVP8 \x18\x00\x00\x000\x01\x00\x9d\x01*\x01\x00\x01\x00\x01@&%\xa4\x00\x03p\x00\xfe\xfd P\x00"
)
WEBP_LOSSLESS = (
    b"RIFF \x00\x00\x00WEBPVP8L\x14\x00\x00\x00/\x00\x00\x00\x00\x07P\x81T\x08 \x00\n\x9a\xfe\xc7\x88\x88\xfe\x07"
)


def test_image_limit_is_ten_mebibytes() -> None:
    assert MAX_IMAGE_BYTES == 10485760
    assert exceeds_image_limit(b"x" * MAX_IMAGE_BYTES) is False
    assert exceeds_image_limit(b"x" * (MAX_IMAGE_BYTES + 1)) is True


def test_declared_rasters_decode_and_mismatched_bytes_do_not() -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), 0)
    png = pixmap.tobytes("png")
    jpeg = pixmap.tobytes("jpeg")
    ensure_decodable_image(png, "image/png")
    ensure_decodable_image(jpeg, "image/jpeg")
    ensure_decodable_image(GIF, "image/gif")
    ensure_decodable_image(WEBP, "image/webp")
    ensure_decodable_image(WEBP_LOSSLESS, "image/webp")
    with pytest.raises(UndecodableImage):
        ensure_decodable_image(b"not-an-image", "image/png")
    with pytest.raises(UndecodableImage):
        ensure_decodable_image(png, "image/jpeg")
    with pytest.raises(UndecodableImage):
        ensure_decodable_image(jpeg[:20], "image/jpeg")
    with pytest.raises(UndecodableImage):
        ensure_decodable_image(b"", "image/gif")
