from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from processor.chunking import PageText, TextTokenizer, build_chunks
from processor.config import Settings, backoff_seconds
from processor.errors import InvalidMessage, PermanentFailure, TransientFailure
from processor.images import UndecodableImage, ensure_decodable_image, exceeds_image_limit
from processor.logging import (
    file_id_var,
    get_logger,
    message_id_var,
    request_id_var,
    user_id_var,
)
from processor.messages import (
    DOCX_CONTENT_TYPE,
    IMAGE_CONTENT_TYPES,
    PDF_CONTENT_TYPE,
    ProcessMessage,
    parse_process_message,
)
from processor.mongo_store import CLAIM_STATUSES, SKIP_STATUSES
from processor.office import CorruptDocument, OfficeUnit, extract_docx, extract_xlsx
from processor.pdfdoc import CorruptPdf, OpenedPdf
from processor.points import image_point_payload, point_id, point_payload
from processor.timeutil import format_z, utcnow


@dataclass(frozen=True)
class DeliveryResult:
    action: str
    requeue: bool = False
    delay_seconds: float = 0.0

    @classmethod
    def ack(cls) -> DeliveryResult:
        return cls("ack")

    @classmethod
    def nack(cls, *, requeue: bool = False, delay_seconds: float = 0.0) -> DeliveryResult:
        return cls("nack", requeue=requeue, delay_seconds=delay_seconds)


class _LeftProcessing(Exception):
    """The file left ``processing`` while this delivery was working."""


def checkpoint_mismatch(checkpoint: dict[str, Any] | None, settings: Settings) -> bool:
    checkpoint = checkpoint or {}
    model = checkpoint.get("embedding_model")
    if model not in (None, "") and model != settings.embedding_model:
        return True
    tokens = checkpoint.get("chunk_tokens")
    if tokens is not None and int(tokens) != settings.chunk_tokens:
        return True
    overlap = checkpoint.get("chunk_overlap")
    if overlap is not None and int(overlap) != settings.chunk_overlap:
        return True
    return False


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        store: Any,
        blobs: Any,
        ocr: Any,
        embedding: Any,
        qdrant: Any,
        tokenizer: TextTokenizer,
        *,
        now: Callable[[], datetime] | None = None,
        heartbeat_seconds: float = 60,
    ) -> None:
        self.settings = settings
        self.store = store
        self.blobs = blobs
        self.ocr = ocr
        self.embedding = embedding
        self.qdrant = qdrant
        self._tokenizer = tokenizer
        self._now = now or utcnow
        self._heartbeat_seconds = heartbeat_seconds

    def handle(
        self,
        body: bytes,
        *,
        redelivered: bool,
        headers: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        headers = headers or {}
        request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
        if not isinstance(request_id, str) or request_id == "":
            request_id = str(uuid.uuid4())
        tokens = [(request_id_var, request_id_var.set(request_id))]
        try:
            try:
                message = parse_process_message(body)
            except InvalidMessage as exc:
                get_logger().error("rejected message", extra={"reason": exc.reason})
                return DeliveryResult.nack()
            tokens.extend(
                [
                    (message_id_var, message_id_var.set(message.message_id)),
                    (file_id_var, file_id_var.set(message.file_id)),
                    (user_id_var, user_id_var.set(message.user_id)),
                ]
            )
            return self._handle_message(message, redelivered=redelivered, request_id=request_id)
        finally:
            for var, token in reversed(tokens):
                var.reset(token)

    def _handle_message(
        self,
        message: ProcessMessage,
        *,
        redelivered: bool,
        request_id: str,
    ) -> DeliveryResult:
        try:
            claimed = self._claim(message)
        except TransientFailure as exc:
            return self._transient(message.file_id, 1, exc)
        if isinstance(claimed, DeliveryResult):
            return claimed
        try:
            attempts = self.store.set_attempts(
                message.file_id,
                reset=not redelivered,
                now=self._now(),
            )
        except TransientFailure as exc:
            return self._transient(message.file_id, 1, exc)
        if attempts is None:
            return self._lost(message, attempts=1)
        if attempts > self.settings.max_process_attempts:
            return self._permanent(message.file_id, "processing_attempts_exceeded")
        try:
            with self._beating(message.file_id):
                self._process(message, request_id)
            return DeliveryResult.ack()
        except PermanentFailure as exc:
            return self._permanent(message.file_id, exc.code)
        except TransientFailure as exc:
            return self._transient(message.file_id, attempts, exc)
        except _LeftProcessing:
            return self._lost(message, attempts=attempts)

    def _claim(self, message: ProcessMessage) -> DeliveryResult | None:
        for _ in range(3):
            file = self.store.get_by_file_id(message.file_id)
            if file is None or file.get("user_id") != message.user_id or file.get("s3_key") != message.s3_key:
                get_logger().error("message does not match file document")
                return DeliveryResult.nack()
            status = file.get("status")
            if status in SKIP_STATUSES:
                get_logger().info("skipped file", extra={"status": status})
                return DeliveryResult.ack()
            if status not in CLAIM_STATUSES:
                return DeliveryResult.nack()
            if self.store.claim(message.file_id, message.user_id, message.s3_key, self._now()):
                return None
        return DeliveryResult.nack()

    def _process(self, message: ProcessMessage, request_id: str) -> None:
        if message.content_type in IMAGE_CONTENT_TYPES:
            self._process_image(message, request_id)
            return
        if message.content_type == PDF_CONTENT_TYPE:
            self._process_pdf(message, request_id)
            return
        self._process_office(message, request_id)

    def _process_pdf(self, message: ProcessMessage, request_id: str) -> None:
        data = self.blobs.get_bytes(message.s3_key)
        try:
            pdf = OpenedPdf(data)
        except CorruptPdf as exc:
            raise PermanentFailure("corrupt_pdf") from exc
        try:
            try:
                page_count = self._extract_pages(pdf, message, request_id)
            except CorruptPdf as exc:
                raise PermanentFailure("corrupt_pdf") from exc
        finally:
            pdf.close()
        pages = self._ordered_pages(message.file_id, page_count)
        chunks = build_chunks(
            pages,
            self._tokenizer,
            size=self.settings.chunk_tokens,
            overlap=self.settings.chunk_overlap_tokens,
        )
        self._index(message, page_count, chunks, request_id)

    def _process_office(self, message: ProcessMessage, request_id: str) -> None:
        data = self.blobs.get_bytes(message.s3_key)
        try:
            if message.content_type == DOCX_CONTENT_TYPE:
                units = extract_docx(data)
            else:
                units = extract_xlsx(data)
        except CorruptDocument as exc:
            raise PermanentFailure("corrupt_document") from exc
        page_count = self._store_office_units(message, units)
        pages = self._ordered_pages(
            message.file_id,
            page_count,
            labels=[unit.label for unit in units],
        )
        chunks = build_chunks(
            pages,
            self._tokenizer,
            size=self.settings.chunk_tokens,
            overlap=self.settings.chunk_overlap_tokens,
        )
        self._index(message, page_count, chunks, request_id)

    def _process_image(self, message: ProcessMessage, request_id: str) -> None:
        data = self.blobs.get_bytes(message.s3_key)
        if exceeds_image_limit(data):
            raise PermanentFailure("image_too_large")
        try:
            ensure_decodable_image(data, message.content_type)
        except UndecodableImage as exc:
            raise PermanentFailure("unsupported_image") from exc
        self._require_processing(message.file_id)
        vector = self.embedding.embed_image(data, request_id)
        if len(vector) == 0:
            raise PermanentFailure("unsupported_image")
        file = self._require_processing(message.file_id)
        s3_key = file["s3_key"]
        point = {
            "id": point_id(message.file_id, 0),
            "vector": vector,
            "payload": image_point_payload(
                file_id=message.file_id,
                user_id=file["user_id"],
                file_name=file["file_name"],
                s3_key=s3_key,
                s3_url=f"s3://{self.settings.s3_bucket}/{s3_key}",
                created_at=format_z(self._now()),
            ),
        }
        self.qdrant.upsert_images([point])
        if not self.store.mark_image_ready(message.file_id, self._now()):
            raise _LeftProcessing()
        get_logger().info("file ready", extra={"content_type": message.content_type})

    def _extract_pages(self, pdf: OpenedPdf, message: ProcessMessage, request_id: str) -> int:
        page_count = pdf.page_count
        if not self.store.note_opened(message.file_id, page_count, self._now()):
            raise _LeftProcessing()
        for number in range(1, page_count + 1):
            if self.store.page_exists(message.file_id, number):
                if not self.store.advance_page(message.file_id, number, self._now()):
                    raise _LeftProcessing()
                continue
            text = pdf.page_text(number)
            if len(text.strip()) > self.settings.min_extracted_chars:
                origin, stored = "text", text
            else:
                png = pdf.render_png(number, self.settings.ocr_render_dpi)
                try:
                    recognized = self.ocr.recognize(png, request_id)
                finally:
                    del png
                if recognized.strip() == "":
                    origin, stored = "empty", ""
                else:
                    origin, stored = "ocr", recognized
            self.store.insert_page(
                {
                    "file_id": message.file_id,
                    "user_id": message.user_id,
                    "page_number": number,
                    "text": stored,
                    "origin": origin,
                    "updated_at": self._now(),
                }
            )
            if not self.store.advance_page(message.file_id, number, self._now()):
                raise _LeftProcessing()
            self.store.touch(message.file_id, self._now())
            get_logger().debug(
                "page stored",
                extra={"page_number": number, "origin": origin, "text_len": len(stored)},
            )
        return page_count

    def _store_office_units(self, message: ProcessMessage, units: list[OfficeUnit]) -> int:
        page_count = len(units)
        if not self.store.note_opened(message.file_id, page_count, self._now()):
            raise _LeftProcessing()
        for number, unit in enumerate(units, start=1):
            if self.store.page_exists(message.file_id, number):
                if not self.store.advance_page(message.file_id, number, self._now()):
                    raise _LeftProcessing()
                continue
            self.store.insert_page(
                {
                    "file_id": message.file_id,
                    "user_id": message.user_id,
                    "page_number": number,
                    "text": unit.text,
                    "origin": "text",
                    "updated_at": self._now(),
                }
            )
            if not self.store.advance_page(message.file_id, number, self._now()):
                raise _LeftProcessing()
            self.store.touch(message.file_id, self._now())
            get_logger().debug(
                "page stored",
                extra={"page_number": number, "origin": "text", "text_len": len(unit.text)},
            )
        return page_count

    def _ordered_pages(
        self,
        file_id: str,
        page_count: int,
        labels: list[str] | None = None,
    ) -> list[PageText]:
        stored = self.store.list_pages(file_id)
        by_number = {int(page["page_number"]): page for page in stored}
        missing = [number for number in range(1, page_count + 1) if number not in by_number]
        if missing:
            raise TransientFailure(
                "page checkpoint incomplete",
                permanent_code="processing_attempts_exceeded",
            )
        return [
            PageText(
                page_number=number,
                text=by_number[number].get("text") or "",
                origin=by_number[number]["origin"],
                unit_label=None if labels is None else labels[number - 1],
            )
            for number in range(1, page_count + 1)
        ]

    def _index(
        self,
        message: ProcessMessage,
        page_count: int,
        chunks: list[Any],
        request_id: str,
    ) -> None:
        if not chunks:
            self.qdrant.delete_file(message.user_id, message.file_id)
            raise PermanentFailure("no_extractable_text")
        file = self._require_processing(message.file_id)
        checkpoint = file.get("checkpoint") or {}
        if checkpoint_mismatch(checkpoint, self.settings):
            self.qdrant.delete_file(message.user_id, message.file_id)
            if not self.store.reset_chunks(message.file_id, self._now()):
                raise _LeftProcessing()
            chunks_done = 0
        else:
            chunks_done = int(checkpoint.get("chunks_done") or 0)
        if chunks_done > len(chunks):
            chunks_done = len(chunks)
        if not self.store.save_chunk_plan(
            message.file_id,
            chunks_total=len(chunks),
            chunks_done=chunks_done,
            embedding_model=self.settings.embedding_model,
            chunk_tokens=self.settings.chunk_tokens,
            chunk_overlap=self.settings.chunk_overlap_tokens,
            now=self._now(),
        ):
            raise _LeftProcessing()
        created_at = format_z(self._now())
        batch_size = self.settings.embedding_batch_size
        while chunks_done < len(chunks):
            file = self._require_processing(message.file_id)
            batch = chunks[chunks_done : chunks_done + batch_size]
            vectors = self.embedding.embed_documents(
                [chunk.text for chunk in batch],
                file["file_name"],
                request_id,
            )
            file = self._require_processing(message.file_id)
            points = [
                {
                    "id": point_id(message.file_id, chunk.index),
                    "vector": vector,
                    "payload": point_payload(
                        text=chunk.text,
                        file_id=message.file_id,
                        user_id=file["user_id"],
                        page_number=chunk.page_number,
                        page_end=chunk.page_end,
                        file_name=file["file_name"],
                        source=chunk.source,
                        chunk_index=chunk.index,
                        created_at=created_at,
                        unit_label=chunk.unit_label,
                    ),
                }
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self.qdrant.upsert_points(points)
            chunks_done += len(batch)
            if not self.store.advance_chunks(message.file_id, chunks_done, self._now()):
                raise _LeftProcessing()
        self.qdrant.delete_tail(message.user_id, message.file_id, len(chunks))
        if not self.store.mark_ready(message.file_id, page_count, self._now()):
            raise _LeftProcessing()
        get_logger().info("file ready", extra={"page_count": page_count, "chunks_total": len(chunks)})

    def _require_processing(self, file_id: str) -> dict[str, Any]:
        file = self.store.get_by_file_id(file_id)
        if file is None or file.get("status") != "processing":
            raise _LeftProcessing()
        return file

    def _lost(self, message: ProcessMessage, *, attempts: int) -> DeliveryResult:
        # processing.md: do not write further points; delete this file's points and ack.
        try:
            if message.content_type in IMAGE_CONTENT_TYPES:
                self.qdrant.delete_image(message.user_id, message.file_id)
            else:
                self.qdrant.delete_file(message.user_id, message.file_id)
        except TransientFailure as exc:
            return self._transient(message.file_id, attempts, exc)
        get_logger().info("stopped because file left processing")
        return DeliveryResult.ack()

    def _transient(self, file_id: str, attempts: int, exc: TransientFailure) -> DeliveryResult:
        get_logger().warning(
            "transient failure",
            extra={"reason": exc.reason, "attempts": attempts, "error_code": exc.permanent_code},
        )
        if attempts >= self.settings.max_process_attempts:
            return self._permanent(file_id, exc.permanent_code)
        return DeliveryResult.nack(requeue=True, delay_seconds=backoff_seconds(attempts))

    def _permanent(self, file_id: str, code: str) -> DeliveryResult:
        now = self._now()
        matched: bool | None = None
        for attempt in range(2):
            try:
                matched = self.store.mark_error(file_id, code, now)
                break
            except TransientFailure as exc:
                if attempt == 0:
                    continue
                get_logger().error(
                    "metadata_update_failed",
                    extra={"error_code": code, "reason": exc.reason},
                )
                return DeliveryResult.nack()
        if matched:
            get_logger().info("permanent failure", extra={"error_code": code})
            return DeliveryResult.nack()
        try:
            file = self.store.get_by_file_id(file_id)
        except TransientFailure as exc:
            get_logger().error(
                "metadata_update_failed",
                extra={"error_code": code, "reason": exc.reason},
            )
            return DeliveryResult.nack()
        if file and file.get("status") in SKIP_STATUSES:
            return DeliveryResult.ack()
        get_logger().error("metadata_update_failed", extra={"error_code": code})
        return DeliveryResult.nack()

    @contextmanager
    def _beating(self, file_id: str):
        if self._heartbeat_seconds <= 0:
            yield
            return
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(self._heartbeat_seconds):
                try:
                    self.store.touch(file_id, self._now())
                except Exception:
                    get_logger().warning("heartbeat failed")

        thread = threading.Thread(target=loop, name="processor-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1)
