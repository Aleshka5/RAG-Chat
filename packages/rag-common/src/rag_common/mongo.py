"""Idempotent MongoDB index declarations from docs/data-models.md.

``create_index`` with the same keys and options is the idempotent start step.
Callers pass an object that supports ``db[name].create_index(keys, **kwargs)``
(PyMongo). This module does not open a connection.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

FILES = "files"
FILE_PAGES = "file_pages"
CHATS = "chats"
MESSAGES = "messages"

# Partial unique indexes ignore status=deleted so the same bytes or s3_key can be stored again.
ACTIVE_FILE_STATUSES = (
    "uploaded",
    "processing",
    "ready",
    "error",
    "deleting",
)


@dataclass(frozen=True)
class IndexSpec:
    keys: tuple[tuple[str, int], ...]
    unique: bool = False
    partial_filter_expression: dict[str, Any] | None = None
    name: str | None = None

    def create(self, collection: Any) -> None:
        kwargs: dict[str, Any] = {}
        if self.unique:
            kwargs["unique"] = True
        if self.partial_filter_expression is not None:
            kwargs["partialFilterExpression"] = self.partial_filter_expression
        # Names match indexes already created by the services. A second name for
        # the same keys makes MongoDB reject startup.
        if self.name is not None:
            kwargs["name"] = self.name
        collection.create_index(list(self.keys), **kwargs)


FILES_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec((("file_id", 1),), unique=True, name="file_id_unique"),
    IndexSpec((("user_id", 1), ("status", 1)), name="user_id_status"),
    IndexSpec((("user_id", 1), ("created_at", -1)), name="user_id_created_at"),
    IndexSpec(
        (("user_id", 1), ("content_sha256", 1)),
        unique=True,
        name="user_id_content_sha256_active",
        partial_filter_expression={"status": {"$in": list(ACTIVE_FILE_STATUSES)}},
    ),
    IndexSpec(
        (("user_id", 1), ("s3_key", 1)),
        unique=True,
        name="user_id_s3_key_active",
        partial_filter_expression={"status": {"$in": list(ACTIVE_FILE_STATUSES)}},
    ),
)

FILE_PAGES_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec(
        (("file_id", 1), ("page_number", 1)),
        unique=True,
        name="file_id_page_number",
    ),
)

CHATS_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec((("chat_id", 1),), unique=True),
    IndexSpec((("user_id", 1), ("updated_at", -1))),
)

MESSAGES_INDEXES: tuple[IndexSpec, ...] = (
    IndexSpec((("message_id", 1),), unique=True),
    IndexSpec((("chat_id", 1), ("created_at", 1))),
    IndexSpec((("user_id", 1), ("created_at", -1))),
)


class SupportsIndexes(Protocol):
    def __getitem__(self, name: str) -> Any: ...


def _ensure(db: SupportsIndexes, collection: str, specs: Sequence[IndexSpec]) -> None:
    target = db[collection]
    for spec in specs:
        spec.create(target)


def ensure_files_indexes(db: SupportsIndexes) -> None:
    """File Collector, Processor, and Deletion Worker."""
    _ensure(db, FILES, FILES_INDEXES)


def ensure_file_pages_indexes(db: SupportsIndexes) -> None:
    """Processor and Deletion Worker."""
    _ensure(db, FILE_PAGES, FILE_PAGES_INDEXES)


def ensure_chats_indexes(db: SupportsIndexes) -> None:
    """Chat, at startup."""
    _ensure(db, CHATS, CHATS_INDEXES)


def ensure_messages_indexes(db: SupportsIndexes) -> None:
    """Chat, at startup."""
    _ensure(db, MESSAGES, MESSAGES_INDEXES)
