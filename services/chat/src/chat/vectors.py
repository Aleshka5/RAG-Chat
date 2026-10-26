import logging
import math
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
    unit_label: str | None = None


@dataclass(slots=True)
class ImageHit:
    file_id: str
    file_name: str
    s3_key: str
    s3_url: str
    score: float
    user_id: str


@dataclass(slots=True)
class ImageScan:
    hits: list[ImageHit]
    scanned: int


class VectorSearch(Protocol):
    async def search(self, user_id: str, vector: list[float], limit: int) -> list[Hit]: ...

    async def search_images(
        self, user_id: str, vector: list[float], limit: int, offset: int
    ) -> ImageScan: ...

    async def close(self) -> None: ...


class QdrantVectorIndex:
    def __init__(self, settings: Settings, client: AsyncQdrantClient | None = None) -> None:
        self._collection = settings.qdrant_collection
        self._images_collection = settings.qdrant_images_collection
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

    async def search_images(
        self, user_id: str, vector: list[float], limit: int, offset: int
    ) -> ImageScan:
        try:
            result = await self._client.query_points(
                collection_name=self._images_collection,
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
                offset=offset,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning(
                "qdrant query failed: %s",
                type(exc).__name__,
                extra={"user_id": user_id},
            )
            raise DependencyUnavailable() from exc
        points = list(result.points)
        hits: list[ImageHit] = []
        for point in points:
            hit = _image_hit_from_point(point)
            if hit is not None:
                hits.append(hit)
        hits.sort(key=lambda item: item.score, reverse=True)
        return ImageScan(hits=hits, scanned=len(points))

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
        unit_label=_required_text(payload, "unit_label"),
    )


def _required_text(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _score_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _image_hit_from_point(point: object) -> ImageHit | None:
    payload = getattr(point, "payload", None) or {}
    if not isinstance(payload, dict):
        return None
    file_id = _required_text(payload, "file_id")
    if file_id is None:
        file_id = _required_text(payload, "document_id")
    file_name = _required_text(payload, "file_name")
    s3_key = _required_text(payload, "s3_key")
    s3_url = _required_text(payload, "s3_url")
    if file_id is None or file_name is None or s3_key is None or s3_url is None:
        return None
    score = _score_value(getattr(point, "score", None))
    if score is None:
        score = _score_value(payload.get("score"))
    if score is None:
        return None
    user_id = payload.get("user_id")
    return ImageHit(
        file_id=file_id,
        file_name=file_name,
        s3_key=s3_key,
        s3_url=s3_url,
        score=score,
        user_id=user_id if isinstance(user_id, str) else "",
    )
