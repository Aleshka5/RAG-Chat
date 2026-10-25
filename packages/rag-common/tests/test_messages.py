import json

import pytest
from pydantic import ValidationError

from rag_common.messages import DocDelete, DocProcess, parse_message

S3_KEY = (
    "files/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/Otchet.pdf"
)

PROCESS = {
    "schema_version": 1,
    "message_type": "doc.process",
    "message_id": "f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5",
    "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
    "user_id": "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
    "s3_key": S3_KEY,
    "file_name": "Отчёт.pdf",
    "content_type": "application/pdf",
    "created_at": "2026-10-18T20:00:00Z",
}

DELETE = {
    "schema_version": 1,
    "message_type": "doc.delete",
    "message_id": "aabbccdd-1122-4333-8444-556677889900",
    "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
    "user_id": "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
    "s3_key": S3_KEY,
    "created_at": "2026-10-18T20:05:00Z",
}


def test_process_example_round_trip() -> None:
    model = DocProcess.model_validate(PROCESS)
    assert model.model_dump() == PROCESS
    assert parse_message(PROCESS).model_dump() == PROCESS


def test_delete_example_round_trip() -> None:
    model = DocDelete.model_validate(DELETE)
    assert model.model_dump() == DELETE
    assert isinstance(parse_message(DELETE), DocDelete)


def test_offset_created_at_serializes_with_z() -> None:
    payload = dict(PROCESS)
    payload["created_at"] = "2026-10-18T23:00:00+03:00"
    dumped = DocProcess.model_validate(payload).model_dump()
    assert dumped["created_at"] == "2026-10-18T20:00:00Z"


def test_rejects_other_schema_string_version_and_x_death() -> None:
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "schema_version": 2})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "schema_version": "1"})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "schema_version": True})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "x-death": [{"count": 1}]})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "content_type": "text/plain"})
    word = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "content_type": word})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "content_type": "application/msword"})


@pytest.mark.parametrize(
    "content_type",
    ["application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"],
)
def test_process_accepts_pdf_and_image_types(content_type: str) -> None:
    model = DocProcess.model_validate({**PROCESS, "content_type": content_type})
    assert model.content_type == content_type
    parsed = parse_message({**PROCESS, "content_type": content_type}).model_dump()
    assert parsed["content_type"] == content_type
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "s3_key": ""})
    with pytest.raises(ValidationError):
        DocProcess.model_validate({**PROCESS, "message_type": "doc.delete"})
    with pytest.raises(ValidationError):
        DocDelete.model_validate({**DELETE, "file_name": "Отчёт.pdf"})
    with pytest.raises(ValidationError):
        parse_message({"message_type": "doc.other"})


def test_naive_created_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DocDelete.model_validate({**DELETE, "created_at": "2026-10-18T20:05:00"})


def test_body_is_utf8_json_without_x_death() -> None:
    raw = json.dumps(DocProcess.model_validate(PROCESS).model_dump(), ensure_ascii=False)
    assert "Отчёт.pdf" in raw
    assert "x-death" not in raw
