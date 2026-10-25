from __future__ import annotations

import uuid
from typing import Any

POINT_NAMESPACE = uuid.UUID("a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65")


def point_id(file_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{file_id}:{chunk_index}"))


def point_payload(
    *,
    text: str,
    file_id: str,
    user_id: str,
    page_number: int,
    page_end: int,
    file_name: str,
    source: str,
    chunk_index: int,
    created_at: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "document_id": file_id,
        "user_id": user_id,
        "page_number": page_number,
        "page_end": page_end,
        "file_name": file_name,
        "source": source,
        "chunk_index": chunk_index,
        "created_at": created_at,
    }


def image_point_payload(
    *,
    file_id: str,
    user_id: str,
    file_name: str,
    s3_key: str,
    s3_url: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "file_id": file_id,
        "document_id": file_id,
        "user_id": user_id,
        "file_name": file_name,
        "s3_key": s3_key,
        "s3_url": s3_url,
        "created_at": created_at,
    }
