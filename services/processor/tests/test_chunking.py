from tests.fakes import CharTokenizer

from processor.chunking import PageText, build_chunks
from processor.errors import ConfigError


def test_spec_window_example() -> None:
    text = "a" * 1200
    chunks = build_chunks(
        [PageText(1, text, "text")],
        CharTokenizer(),
        size=512,
        overlap=51,
    )
    assert [chunk.text for chunk in chunks] == [text[0:512], text[461:973], text[922:1200]]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]
    assert chunks[2].page_number == 1
    assert chunks[2].page_end == 1
    assert all(chunk.source == "text" for chunk in chunks)


def test_page_of_first_and_last_token_and_ocr_source() -> None:
    pages = [
        PageText(1, "a" * 400, "text"),
        PageText(2, "", "empty"),
        PageText(3, "b" * 800, "ocr"),
    ]
    chunks = build_chunks(pages, CharTokenizer(), size=512, overlap=51)
    assert chunks[0].page_number == 1
    assert chunks[0].page_end == 3
    assert chunks[0].source == "ocr"
    assert chunks[0].text == ("a" * 400) + ("b" * 112)


def test_empty_decoded_window_does_not_consume_chunk_index() -> None:
    class BlankThenLetter:
        def encode(self, text: str) -> list[int]:
            return [0 if char == " " else 65 for char in text]

        def decode(self, token_ids: list[int]) -> str:
            return "".join(" " if token_id == 0 else "A" for token_id in token_ids)

    chunks = build_chunks(
        [PageText(1, "  A", "text")],
        BlankThenLetter(),
        size=2,
        overlap=0,
    )
    assert [chunk.index for chunk in chunks] == [0]
    assert chunks[0].text.strip() == "A"


def test_overlap_not_smaller_than_window_refuses_to_start() -> None:
    try:
        build_chunks([PageText(1, "abc", "text")], CharTokenizer(), size=2, overlap=2)
    except ConfigError as exc:
        assert "CHUNK_OVERLAP" in str(exc)
    else:
        raise AssertionError("expected ConfigError")
