from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from processor.errors import PermanentFailure, TransientFailure
from processor.mongo_store import EMPTY_CHECKPOINT


class MemoryFiles:
    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = {}
        self.pages: dict[tuple[str, int], dict[str, Any]] = {}
        self.pages_done_history: list[int] = []

    def add(self, document: dict[str, Any]) -> None:
        self.files[document["file_id"]] = copy.deepcopy(document)

    def get_by_file_id(self, file_id: str) -> dict[str, Any] | None:
        file = self.files.get(file_id)
        return copy.deepcopy(file) if file is not None else None

    def claim(self, file_id: str, user_id: str, s3_key: str, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["user_id"] != user_id or file["s3_key"] != s3_key:
            return False
        if file["status"] not in ("uploaded", "error", "processing"):
            return False
        file["status"] = "processing"
        file["error"] = None
        file["updated_at"] = now
        if file.get("checkpoint") is None:
            file["checkpoint"] = copy.deepcopy(EMPTY_CHECKPOINT)
        return True

    def set_attempts(self, file_id: str, *, reset: bool, now: datetime) -> int | None:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return None
        checkpoint = file["checkpoint"]
        if reset:
            checkpoint["process_attempts"] = 1
        else:
            checkpoint["process_attempts"] = int(checkpoint.get("process_attempts") or 0) + 1
        file["updated_at"] = now
        return int(checkpoint["process_attempts"])

    def mark_error(self, file_id: str, code: str, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        file["status"] = "error"
        file["error"] = code
        file["updated_at"] = now
        return True

    def touch(self, file_id: str, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        file["updated_at"] = now
        return True

    def note_opened(self, file_id: str, page_count: int, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        file["page_count"] = page_count
        file["checkpoint"]["pages_total"] = page_count
        file["updated_at"] = now
        return True

    def page_exists(self, file_id: str, page_number: int) -> bool:
        return (file_id, page_number) in self.pages

    def insert_page(self, page: dict[str, Any]) -> None:
        key = (page["file_id"], page["page_number"])
        if key in self.pages:
            return
        self.pages[key] = copy.deepcopy(page)

    def list_pages(self, file_id: str) -> list[dict[str, Any]]:
        rows = [copy.deepcopy(page) for (owner, _), page in self.pages.items() if owner == file_id]
        return sorted(rows, key=lambda page: page["page_number"])

    def advance_page(self, file_id: str, page_number: int, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        current = int(file["checkpoint"].get("pages_done") or 0)
        file["checkpoint"]["pages_done"] = max(current, page_number)
        file["updated_at"] = now
        self.pages_done_history.append(file["checkpoint"]["pages_done"])
        return True

    def save_chunk_plan(
        self,
        file_id: str,
        *,
        chunks_total: int,
        chunks_done: int,
        embedding_model: str,
        chunk_tokens: int,
        chunk_overlap: int,
        now: datetime,
    ) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        checkpoint = file["checkpoint"]
        checkpoint["chunks_total"] = chunks_total
        checkpoint["chunks_done"] = chunks_done
        checkpoint["embedding_model"] = embedding_model
        checkpoint["chunk_tokens"] = chunk_tokens
        checkpoint["chunk_overlap"] = chunk_overlap
        file["updated_at"] = now
        return True

    def advance_chunks(self, file_id: str, chunks_done: int, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        current = int(file["checkpoint"].get("chunks_done") or 0)
        file["checkpoint"]["chunks_done"] = max(current, chunks_done)
        file["updated_at"] = now
        return True

    def reset_chunks(self, file_id: str, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        checkpoint = file["checkpoint"]
        checkpoint["chunks_done"] = 0
        checkpoint["chunks_total"] = None
        checkpoint["embedding_model"] = None
        checkpoint["chunk_tokens"] = None
        checkpoint["chunk_overlap"] = None
        file["updated_at"] = now
        return True

    def mark_ready(self, file_id: str, page_count: int, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        file["status"] = "ready"
        file["error"] = None
        file["page_count"] = page_count
        file["updated_at"] = now
        return True

    def mark_image_ready(self, file_id: str, now: datetime) -> bool:
        file = self.files.get(file_id)
        if file is None or file["status"] != "processing":
            return False
        file["status"] = "ready"
        file["error"] = None
        file["updated_at"] = now
        return True

    def find_enqueue_failed(self, older_than: datetime) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(file)
            for file in self.files.values()
            if file["status"] == "error" and file["error"] == "enqueue_failed" and file["updated_at"] < older_than
        ]


class MemoryBlobs:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reads: list[str] = []

    def get_bytes(self, key: str) -> bytes:
        self.reads.append(key)
        return self.data


class FakeOcr:
    def __init__(self, text: str = "распознанный текст страницы") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def recognize(self, png: bytes, request_id: str) -> str:
        self.calls.append({"png": png, "request_id": request_id})
        return self.text


class FakeEmbed:
    def __init__(
        self,
        dimension: int,
        on_call: Any = None,
        *,
        on_image: Any = None,
        image_status: int | None = None,
        image_vector: list[float] | None = None,
    ) -> None:
        self.dimension = dimension
        self.on_call = on_call
        self.on_image = on_image
        self.image_status = image_status
        self.image_vector = image_vector
        self.calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []

    def embed_documents(self, texts: list[str], title: str, request_id: str) -> list[list[float]]:
        self.calls.append(
            {
                "path": "/embed",
                "texts": list(texts),
                "title": title,
                "request_id": request_id,
                "input_type": "document",
            }
        )
        if self.on_call is not None:
            self.on_call(texts, title, request_id)
        return [[float(index + 1)] * self.dimension for index in range(len(texts))]

    def embed_image(self, image: bytes, request_id: str) -> list[float]:
        self.image_calls.append({"path": "/embed/image", "image": image, "request_id": request_id})
        if self.on_image is not None:
            self.on_image(image, request_id)
        if self.image_status == 400:
            raise PermanentFailure("embedding_failed")
        if self.image_status is not None and 500 <= self.image_status <= 599:
            raise TransientFailure(
                f"embedding http {self.image_status}",
                permanent_code="embedding_failed",
            )
        if self.image_vector is not None:
            return list(self.image_vector)
        return [1.0] * self.dimension


class FakeQdrant:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, Any]] = {}
        self.image_points: dict[str, dict[str, Any]] = {}
        self.ops: list[tuple] = []
        self.fail_upserts = 0
        self.fail_deletes = 0

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        self.ops.append(("upsert", len(points)))
        if self.fail_upserts:
            self.fail_upserts -= 1
            raise TransientFailure("qdrant", permanent_code="index_write_failed")
        for point in points:
            self.points[point["id"]] = point

    def delete_file(self, user_id: str, document_id: str) -> None:
        self.ops.append(("delete_file", user_id, document_id))
        if self.fail_deletes:
            self.fail_deletes -= 1
            raise TransientFailure("qdrant", permanent_code="index_write_failed")
        self._drop(user_id, document_id, None)

    def upsert_images(self, points: list[dict[str, Any]]) -> None:
        self.ops.append(("upsert_images", len(points)))
        if self.fail_upserts:
            self.fail_upserts -= 1
            raise TransientFailure("qdrant", permanent_code="index_write_failed")
        for point in points:
            self.image_points[point["id"]] = point

    def delete_image(self, user_id: str, document_id: str) -> None:
        self.ops.append(("delete_image", user_id, document_id))
        if self.fail_deletes:
            self.fail_deletes -= 1
            raise TransientFailure("qdrant", permanent_code="index_write_failed")
        drop = [
            key
            for key, point in self.image_points.items()
            if point["payload"].get("user_id") == user_id and point["payload"].get("document_id") == document_id
        ]
        for key in drop:
            del self.image_points[key]

    def delete_tail(self, user_id: str, document_id: str, chunk_index_gte: int) -> None:
        self.ops.append(("delete_tail", user_id, document_id, chunk_index_gte))
        if self.fail_deletes:
            self.fail_deletes -= 1
            raise TransientFailure("qdrant", permanent_code="index_write_failed")
        self._drop(user_id, document_id, chunk_index_gte)

    def _drop(self, user_id: str, document_id: str, chunk_index_gte: int | None) -> None:
        drop = []
        for key, point in self.points.items():
            payload = point["payload"]
            if payload["user_id"] != user_id or payload["document_id"] != document_id:
                continue
            if chunk_index_gte is None or payload["chunk_index"] >= chunk_index_gte:
                drop.append(key)
        for key in drop:
            del self.points[key]


class CharTokenizer:
    def encode(self, text: str) -> list[int]:
        return [ord(char) for char in text]

    def decode(self, token_ids: list[int]) -> str:
        return "".join(chr(token_id) for token_id in token_ids)
