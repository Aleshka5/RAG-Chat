import logging
from dataclasses import dataclass
from typing import Protocol

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from chat.config import Settings
from chat.errors import DependencyUnavailable

logger = logging.getLogger("chat")


@dataclass(slots=True)
class Hit:
    document_id: str
    user_id: str
    text: str
    page_number: int
    chunk_index: int
    score: float


class VectorSearch(Protocol):
    async def search(self, user_id: str, vector: list[float], limit: int) -> list[Hit]: ...

    async def close(self) -> None: ...


class QdrantVectorIndex:
    def __init__(self, settings: Settings, client: AsyncQdrantClient | None = None) -> None:
        self._collection = settings.qdrant_collection
        self._client = client or AsyncQdrantClient(url=settings.qdrant_url)
        self._owns_client = client is None

    async def search(self, user_id: str, vector: list[float], limit: int) -> list[Hit]:
        try:
            result = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="user_id",
                            match=models.MatchValue(value=user_id),
                        )
                    ]
                ),
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning(
                "qdrant query failed: %s",
                type(exc).__name__,
                extra={"user_id": user_id},
            )
            raise DependencyUnavailable() from exc
        hits: list[Hit] = []
        for point in result.points:
            hit = _hit_from_point(point)
            if hit is not None:
                hits.append(hit)
        return hits

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def _hit_from_point(point: object) -> Hit | None:
    payload = getattr(point, "payload", None) or {}
    if not isinstance(payload, dict):
        return None
    document_id = payload.get("document_id")
    text = payload.get("text")
    page_number = _as_int(payload.get("page_number"))
    chunk_index = _as_int(payload.get("chunk_index"))
    if not isinstance(document_id, str) or not document_id:
        return None
    if not isinstance(text, str):
        return None
    if page_number is None or chunk_index is None:
        return None
    raw_score = getattr(point, "score", None)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    user_id = payload.get("user_id")
    return Hit(
        document_id=document_id,
        user_id=user_id if isinstance(user_id, str) else "",
        text=text,
        page_number=page_number,
        chunk_index=chunk_index,
        score=score,
    )
