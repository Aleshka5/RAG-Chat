import json
from datetime import UTC, datetime, timedelta

import pytest

from deletion_worker.handler import DeletionHandler
from deletion_worker.model import FileRecord
from tests.fakes import MemoryFiles, MemoryObjects, MemoryVectors

FILE_ID = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
USER_ID = "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d"
MESSAGE_ID = "aabbccdd-1122-4333-8444-556677889900"
S3_KEY = (
    "files/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/Otchet.pdf"
)
NOW = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)


def delete_body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "schema_version": 1,
        "message_type": "doc.delete",
        "message_id": MESSAGE_ID,
        "file_id": FILE_ID,
        "user_id": USER_ID,
        "s3_key": S3_KEY,
        "created_at": "2026-10-18T20:05:00Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def snapshot(
    files: MemoryFiles,
    objects: MemoryObjects,
    vectors: MemoryVectors,
) -> dict[str, object]:
    return {
        "docs": {key: replace_record(value) for key, value in files.docs.items()},
        "pages": {key: list(value) for key, value in files.pages.items()},
        "objects": dict(objects.objects),
        "points": {key: list(value) for key, value in vectors.points.items()},
    }


def replace_record(record: FileRecord) -> FileRecord:
    return FileRecord(
        file_id=record.file_id,
        user_id=record.user_id,
        s3_key=record.s3_key,
        status=record.status,
        updated_at=record.updated_at,
        delete_claimed_at=record.delete_claimed_at,
        error=record.error,
        object_owner=record.object_owner,
    )


class World:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.files = MemoryFiles(self.events)
        self.objects = MemoryObjects(self.events)
        self.vectors = MemoryVectors(self.events)
        self.sleeps: list[float] = []
        self.handler = DeletionHandler(
            self.files,
            self.objects,
            self.vectors,
            stale_processing_seconds=900,
            clock=lambda: NOW,
            sleep=self.sleeps.append,
        )

    def add_file(
        self,
        *,
        status: str = "deleting",
        updated_at: datetime | None = None,
        delete_claimed_at: datetime | None = None,
        s3_key: str = S3_KEY,
        user_id: str = USER_ID,
        error: str | None = None,
        object_owner: str = "rag",
    ) -> None:
        self.files.docs[FILE_ID] = FileRecord(
            file_id=FILE_ID,
            user_id=user_id,
            s3_key=s3_key,
            status=status,
            updated_at=NOW if updated_at is None else updated_at,
            delete_claimed_at=delete_claimed_at,
            error=error,
            object_owner=object_owner,
        )
        self.objects.objects[s3_key] = b"%PDF-1.7"
        self.vectors.points[(user_id, FILE_ID)] = ["point-a", "point-b"]
        self.files.pages[FILE_ID] = [
            {"file_id": FILE_ID, "page_number": 1, "text": "page"},
            {"file_id": FILE_ID, "page_number": 2, "text": "more"},
        ]


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def message() -> bytes:
    return delete_body()


def stale_time() -> datetime:
    return NOW - timedelta(seconds=901)
