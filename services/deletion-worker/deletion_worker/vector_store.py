from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import FieldCondition, Filter, FilterSelector, MatchValue

from deletion_worker.errors import TransientStorageError


class QdrantVectorStore:
    def __init__(self, client: Any, collection: str) -> None:
        self._client = client
        self._collection = collection

    def delete_points(self, user_id: str, document_id: str) -> None:
        selector = FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                ]
            )
        )
        try:
            self._client.delete(
                collection_name=self._collection,
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
