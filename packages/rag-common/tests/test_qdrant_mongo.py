from uuid import UUID, uuid5

from rag_common.mongo import (
    ACTIVE_FILE_STATUSES,
    CHATS_INDEXES,
    FILE_PAGES_INDEXES,
    FILES_INDEXES,
    MESSAGES_INDEXES,
    ensure_chats_indexes,
    ensure_file_pages_indexes,
    ensure_files_indexes,
    ensure_messages_indexes,
)
from rag_common.qdrant import (
    COLLECTION_NAME,
    DISTANCE,
    DOCUMENT_PAYLOAD_KEY,
    HNSW_M,
    HNSW_PAYLOAD_M,
    IMAGES_COLLECTION_NAME,
    POINT_ID_NAMESPACE,
    TENANT_PAYLOAD_KEY,
    point_id,
)


def test_point_id_formula() -> None:
    file_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    assert POINT_ID_NAMESPACE == UUID("a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65")
    assert point_id(file_id, 0) == uuid5(POINT_ID_NAMESPACE, f"{file_id}:0")
    assert point_id(file_id.upper(), 3) == point_id(file_id, 3)
    assert point_id(file_id, 0) != point_id(file_id, 1)
    assert COLLECTION_NAME == "documents"
    assert IMAGES_COLLECTION_NAME == "images"
    assert TENANT_PAYLOAD_KEY == "user_id"
    assert DOCUMENT_PAYLOAD_KEY == "document_id"
    assert DISTANCE == "cosine"
    assert HNSW_M == 0
    assert HNSW_PAYLOAD_M == 16


def test_point_id_rejects_negative_chunk() -> None:
    try:
        point_id("6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f", -1)
    except ValueError:
        return
    raise AssertionError("chunk_index starts at 0")


class FakeCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[list, dict]] = []

    def create_index(self, keys, **kwargs) -> str:
        self.calls.append((list(keys), kwargs))
        return "ok"


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


def test_indexes_are_idempotent_and_match_data_models() -> None:
    db = FakeDB()
    ensure_files_indexes(db)
    ensure_files_indexes(db)
    ensure_file_pages_indexes(db)
    ensure_chats_indexes(db)
    ensure_messages_indexes(db)

    files = db["files"].calls
    assert files[0] == ([("file_id", 1)], {"unique": True, "name": "file_id_unique"})
    assert files[1] == ([("user_id", 1), ("status", 1)], {"name": "user_id_status"})
    assert files[2] == (
        [("user_id", 1), ("created_at", -1)],
        {"name": "user_id_created_at"},
    )
    partial = {"status": {"$in": list(ACTIVE_FILE_STATUSES)}}
    assert files[3] == (
        [("user_id", 1), ("content_sha256", 1)],
        {
            "unique": True,
            "partialFilterExpression": partial,
            "name": "user_id_content_sha256_active",
        },
    )
    assert files[4] == (
        [("user_id", 1), ("s3_key", 1)],
        {
            "unique": True,
            "partialFilterExpression": partial,
            "name": "user_id_s3_key_active",
        },
    )
    assert "deleted" not in ACTIVE_FILE_STATUSES
    assert files[5:] == files[:5]

    assert db["file_pages"].calls == [
        (
            [("file_id", 1), ("page_number", 1)],
            {"unique": True, "name": "file_id_page_number"},
        ),
    ]
    assert [spec.keys for spec in FILE_PAGES_INDEXES] == [(("file_id", 1), ("page_number", 1))]
    assert [spec.keys for spec in CHATS_INDEXES] == [
        (("chat_id", 1),),
        (("user_id", 1), ("updated_at", -1)),
    ]
    assert [spec.keys for spec in MESSAGES_INDEXES] == [
        (("message_id", 1),),
        (("chat_id", 1), ("created_at", 1)),
        (("user_id", 1), ("created_at", -1)),
    ]
    assert len(FILES_INDEXES) == 5
    assert FILES_INDEXES[4].keys == (("user_id", 1), ("s3_key", 1))
    assert FILES_INDEXES[4].unique is True
    assert FILES_INDEXES[4].name == "user_id_s3_key_active"
    assert FILES_INDEXES[4].partial_filter_expression == {
        "status": {"$in": ["uploaded", "processing", "ready", "error", "deleting"]}
    }
