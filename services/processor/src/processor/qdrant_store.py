from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from qdrant_client import QdrantClient, models

from processor.config import Settings
from processor.errors import TransientFailure
from processor.logging import get_logger
from processor.retry import retry_call


def file_points_filter(user_id: str, document_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id)),
        ]
    )


def tail_points_filter(user_id: str, document_id: str, chunk_index_gte: int) -> models.Filter:
    base = file_points_filter(user_id, document_id)
    return models.Filter(
        must=[
            *base.must,
            models.FieldCondition(key="chunk_index", range=models.Range(gte=chunk_index_gte)),
        ]
    )


def vector_size(info: Any) -> int:
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        if not vectors:
            raise RuntimeError("qdrant collection has no vectors")
        first = next(iter(vectors.values()))
        return int(first.size)
    return int(vectors.size)


class QdrantStore:
    def __init__(
        self,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        attempts: int = 3,
        client: QdrantClient | None = None,
    ) -> None:
        self._documents = settings.qdrant_collection
        self._images = settings.qdrant_images_collection
        self._dim = settings.embedding_dim
        self._upsert_batch = settings.qdrant_upsert_batch
        self._sleep = sleeper
        self._attempts = attempts
        self._client = client or QdrantClient(url=settings.qdrant_url, timeout=30)

    def ensure_collection(self) -> None:
        self._ensure_one(self._documents)
        self._ensure_one(self._images)

    def _ensure_one(self, name: str) -> None:
        exists = self._client.collection_exists(collection_name=name)
        if not exists:
            self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=self._dim,
                    distance=models.Distance.COSINE,
                ),
                hnsw_config=models.HnswConfigDiff(payload_m=16, m=0),
            )
        else:
            info = self._client.get_collection(collection_name=name)
            actual = vector_size(info)
            if actual != self._dim:
                get_logger().error(
                    "qdrant vector size does not match EMBEDDING_DIM",
                    extra={"expected": self._dim, "actual": actual, "collection": name},
                )
                raise SystemExit(1)
        info = self._client.get_collection(collection_name=name)
        fields = set((getattr(info, "payload_schema", None) or {}).keys())
        if "user_id" not in fields:
            self._client.create_payload_index(
                collection_name=name,
                field_name="user_id",
                field_schema=models.KeywordIndexParams(
                    type=models.KeywordIndexType.KEYWORD,
                    is_tenant=True,
                ),
            )
        if "document_id" not in fields:
            self._client.create_payload_index(
                collection_name=name,
                field_name="document_id",
                field_schema=models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
            )
        if name == self._documents and "unit_label" not in fields:
            self._client.create_payload_index(
                collection_name=name,
                field_name="unit_label",
                field_schema=models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
            )

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        self._upsert(self._documents, points)

    def upsert_images(self, points: list[dict[str, Any]]) -> None:
        self._upsert(self._images, points)

    def delete_file(self, user_id: str, document_id: str) -> None:
        self._delete(self._documents, file_points_filter(user_id, document_id))

    def delete_image(self, user_id: str, document_id: str) -> None:
        self._delete(self._images, file_points_filter(user_id, document_id))

    def delete_tail(self, user_id: str, document_id: str, chunk_index_gte: int) -> None:
        self._delete(self._documents, tail_points_filter(user_id, document_id, chunk_index_gte))

    def _upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        for offset in range(0, len(points), self._upsert_batch):
            batch = points[offset : offset + self._upsert_batch]
            structs = [
                models.PointStruct(id=point["id"], vector=point["vector"], payload=point["payload"]) for point in batch
            ]

            def once(structs: list[models.PointStruct] = structs, collection: str = collection) -> None:
                self._client.upsert(collection_name=collection, points=structs, wait=True)

            self._run(once)

    def _delete(self, collection: str, point_filter: models.Filter) -> None:
        selector = models.FilterSelector(filter=point_filter)

        def once() -> None:
            self._client.delete(collection_name=collection, points_selector=selector, wait=True)

        self._run(once)

    def _run(self, operation: Callable[[], None]) -> None:
        try:
            retry_call(
                operation,
                attempts=self._attempts,
                sleeper=self._sleep,
                is_retryable=lambda exc: not isinstance(exc, (KeyboardInterrupt, SystemExit)),
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise TransientFailure("qdrant", permanent_code="index_write_failed") from exc
