import uuid

from qdrant_client import models

from processor.points import POINT_NAMESPACE, point_id
from processor.qdrant_store import file_points_filter, tail_points_filter, vector_size


def test_point_id_is_uuid5_of_file_and_chunk() -> None:
    file_id = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
    expected = str(uuid.uuid5(POINT_NAMESPACE, f"{file_id}:2"))
    assert POINT_NAMESPACE == uuid.UUID("a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65")
    assert point_id(file_id, 2) == expected
    assert point_id(file_id, 2) == point_id(file_id, 2)
    assert point_id(file_id, 2) != point_id(file_id, 3)


def test_delete_filter_is_tenant_plus_document() -> None:
    filt = file_points_filter("user-1", "file-1")
    assert [item.key for item in filt.must] == ["user_id", "document_id"]
    assert filt.must[0].match.value == "user-1"
    assert filt.must[1].match.value == "file-1"


def test_tail_filter_keeps_lower_chunk_indexes() -> None:
    filt = tail_points_filter("user-1", "file-1", 4)
    assert [item.key for item in filt.must] == ["user_id", "document_id", "chunk_index"]
    assert filt.must[2].range.gte == 4


def test_vector_size_reads_unnamed_and_named_configs() -> None:
    unnamed = type("Info", (), {})()
    unnamed.config = type("C", (), {})()
    unnamed.config.params = type("P", (), {"vectors": type("V", (), {"size": 768})()})()
    assert vector_size(unnamed) == 768
    named = type("Info", (), {})()
    named.config = type("C", (), {})()
    named.config.params = type(
        "P",
        (),
        {"vectors": {"dense": type("V", (), {"size": 768})()}},
    )()
    assert vector_size(named) == 768
    assert models.Distance.COSINE.value == "Cosine"
