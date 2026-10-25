from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import FieldCondition, Filter, FilterSelector, MatchValue

from deletion_worker.errors import TransientStorageError


class QdrantVectorStore:
    def __init__(self, client: Any, collection: str, images_collection: str) -> None:
        self._client = client
        self._collections = (collection, images_collection)

    def delete_points(self, user_id: str, document_id: str) -> None:
        selector = _points_selector(user_id, document_id)
        for collection in self._collections:
            self._delete_collection(collection, selector)

    def _delete_collection(self, collection: str, selector: FilterSelector) -> None:
        try:
            self._client.delete(
                collection_name=collection,
                points_selector=selector,
                wait=True,
            )
        except UnexpectedResponse as exc:
            if getattr(exc, "status_code", None) == 404:
                return
            raise TransientStorageError("qdrant") from exc
        except Exception as exc:
            raise TransientStorageError("qdrant") from exc


def connect_qdrant(url: str) -> QdrantClient:
    return QdrantClient(url=url, timeout=30, prefer_grpc=False)


def _points_selector(user_id: str, document_id: str) -> FilterSelector:
    return FilterSelector(
        filter=Filter(
            must=[
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )
    )
