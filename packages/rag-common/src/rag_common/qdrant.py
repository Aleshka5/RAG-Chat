"""Qdrant collection identity from docs/data-models.md.

Document chunks live in ``QDRANT_COLLECTION``. One image file is one point in
``QDRANT_IMAGES_COLLECTION``. The tenant payload field is ``user_id``.
Point ids are ``uuid5(namespace, "{file_id}:{chunk_index}")`` so a retry
overwrites the same point. An image uses chunk index 0. Vector size is
``EMBEDDING_DIM``, not a second constant.
"""

from uuid import UUID, uuid5

from rag_common.config import DEFAULTS

COLLECTION_NAME = DEFAULTS["QDRANT_COLLECTION"]
IMAGES_COLLECTION_NAME = DEFAULTS["QDRANT_IMAGES_COLLECTION"]
TENANT_PAYLOAD_KEY = "user_id"
DOCUMENT_PAYLOAD_KEY = "document_id"
POINT_ID_NAMESPACE = UUID("a5b3c1d2-6e47-5f80-9c11-0d4e8f2a7b65")

# models.Distance.COSINE, HnswConfigDiff(payload_m=16, m=0)
DISTANCE = "cosine"
HNSW_PAYLOAD_M = 16
HNSW_M = 0


def point_id(file_id: str, chunk_index: int) -> UUID:
    """Stable point id for one chunk of one file."""
    canonical = UUID(file_id)
    if type(chunk_index) is not int or chunk_index < 0:
        raise ValueError("chunk_index starts at 0")
    return uuid5(POINT_ID_NAMESPACE, f"{canonical}:{chunk_index}")
