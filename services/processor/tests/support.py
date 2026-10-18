from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pymupdf
from tests.fakes import CharTokenizer, FakeEmbed, FakeOcr, FakeQdrant, MemoryBlobs, MemoryFiles

from processor.config import Settings, validate_settings
from processor.pipeline import Pipeline

FILE_ID = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
USER_ID = "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d"


def clock_now() -> datetime:
    return datetime(2026, 10, 18, 20, 0, tzinfo=UTC)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "mongodb_uri": "mongodb://mongo:27017/rag",
        "s3_endpoint": "http://minio:9000",
        "s3_access_key": "access",
        "s3_secret_key": "secret",
        "qdrant_url": "http://qdrant:6333",
        "rabbitmq_url": "amqp://rabbit:5672/",
        "embedding_url": "http://embedding:8091",
        "ocr_url": "http://ocr:8090",
        "chunk_tokens": 32,
        "chunk_overlap_tokens": 4,
        "embedding_dim": 4,
        "embedding_batch_size": 16,
        "ocr_render_dpi": 72,
        "min_extracted_chars": 50,
        "embedding_model": "google/embeddinggemma-2",
    }
    values.update(overrides)
    settings = Settings(**values)
    validate_settings(settings)
    return settings


def file_document(**overrides: Any) -> dict[str, Any]:
    file_id = overrides.get("file_id", FILE_ID)
    user_id = overrides.get("user_id", USER_ID)
    document: dict[str, Any] = {
        "file_id": file_id,
        "user_id": user_id,
        "file_name": "Отчёт.pdf",
        "safe_name": "Otchet.pdf",
        "file_size": 1200,
        "content_type": "application/pdf",
        "content_sha256": "ab" * 32,
        "s3_key": f"files/{user_id}/{file_id}/Otchet.pdf",
        "status": "uploaded",
        "page_count": None,
        "error": None,
        "delete_claimed_at": None,
        "created_at": clock_now(),
        "updated_at": clock_now(),
        "checkpoint": {
            "pages_done": 0,
            "pages_total": None,
            "chunks_done": 0,
            "chunks_total": None,
            "process_attempts": 0,
            "embedding_model": None,
            "chunk_tokens": None,
            "chunk_overlap": None,
        },
    }
    if "checkpoint" in overrides:
        document["checkpoint"].update(overrides.pop("checkpoint"))
    document.update(overrides)
    return document


def pdf_bytes(pages: list[str]) -> bytes:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


def message_for(document: dict[str, Any], **overrides: Any) -> bytes:
    body: dict[str, Any] = {
        "schema_version": 1,
        "message_type": "doc.process",
        "message_id": str(uuid.uuid4()),
        "file_id": document["file_id"],
        "user_id": document["user_id"],
        "s3_key": document["s3_key"],
        "file_name": "from-message.pdf",
        "content_type": "application/pdf",
        "created_at": "2026-10-18T20:00:00Z",
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def build_pipeline(
    settings: Settings,
    store: MemoryFiles,
    blobs: MemoryBlobs,
    *,
    ocr: FakeOcr | None = None,
    embedding: FakeEmbed | None = None,
    qdrant: FakeQdrant | None = None,
) -> tuple[Pipeline, FakeOcr, FakeEmbed, FakeQdrant]:
    ocr = ocr or FakeOcr()
    embedding = embedding or FakeEmbed(settings.embedding_dim)
    qdrant = qdrant or FakeQdrant()
    pipeline = Pipeline(
        settings,
        store,
        blobs,
        ocr,
        embedding,
        qdrant,
        CharTokenizer(),
        now=clock_now,
        heartbeat_seconds=0,
    )
    return pipeline, ocr, embedding, qdrant
