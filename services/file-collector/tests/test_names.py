import pytest
from file_collector.names import content_disposition, safe_name, validated_file_name


def test_safe_name_keeps_unicode_letters_and_forces_pdf_extension() -> None:
    assert safe_name("Отчёт.pdf") == "Отчёт.pdf"
    assert safe_name("my report.pdf") == "my_report.pdf"
    assert safe_name("a___b.txt") == "a_b.pdf"
    assert safe_name("weird?.txt") == "weird_.pdf"
    assert safe_name("file.PDF") == "file.pdf"
    assert safe_name("../../etc/passwd") == "passwd.pdf"
    assert safe_name("") == "document.pdf"
    assert safe_name("C:\\docs\\a.pdf") == "a.pdf"


def test_safe_name_stays_within_200_characters() -> None:
    named = safe_name("a" * 250)
    assert named.endswith(".pdf")
    assert len(named) <= 200


def test_validated_file_name_keeps_basename() -> None:
    assert validated_file_name("../../Отчёт.pdf") == "Отчёт.pdf"
    assert validated_file_name("note.pdf") == "note.pdf"
    with pytest.raises(ValueError):
        validated_file_name(None)
    with pytest.raises(ValueError):
        validated_file_name("..")
    with pytest.raises(ValueError):
        validated_file_name("a" * 256)
    with pytest.raises(ValueError):
        validated_file_name("bad\nname.pdf")


def test_content_disposition_has_ascii_fallback_and_utf8_star() -> None:
    header = content_disposition("Отчёт.pdf")
    assert header.startswith("inline; ")
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert "%" in header.split("filename*=UTF-8''", 1)[1]
    plain = content_disposition("note.pdf")
    assert 'filename="note.pdf"' in plain
    assert "filename*=UTF-8''note.pdf" in plain
