"""Upload, list, content, and delete use cases."""

import hashlib
import logging
import tempfile
import uuid
from typing import BinaryIO

from fastapi import Request
from starlette.datastructures import UploadFile

from file_collector.clock import utcnow
from file_collector.config import Settings
from file_collector.errors import (
    ApiError,
    DuplicateActiveFile,
    PublishError,
    StorageError,
)
from file_collector.messages import delete_publication, process_publication
from file_collector.names import content_disposition, safe_name, validated_file_name
from file_collector.schema import CONTENT_STATUSES, file_card, new_file_document

logger = logging.getLogger("file_collector")


async def upload_pdf(
    *,
    request: Request,
    user_id: str,
    request_id: str,
    settings: Settings,
    files,
    objects,
    publisher,
) -> dict:
    limit = settings.max_upload_bytes
    form = None
    spool = None
    try:
        form = await _parse_form(request, limit)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ApiError(400, "validation_error", "Invalid request", {"fields": ["file"]})
        if upload.size is not None and upload.size > limit:
            raise ApiError(413, "file_too_large", "File exceeds the size limit")
        spool, size = await _read_limited(upload, limit)
        try:
            file_name = validated_file_name(upload.filename)
        except ValueError as exc:
            raise ApiError(
                400,
                "validation_error",
                "Invalid request",
                {"fields": ["file"]},
            ) from exc
        if not _is_pdf(spool):
            raise ApiError(415, "unsupported_media_type", "Only PDF is accepted")
        digest = _sha256(spool)
        logger.debug(
            "upload sha256 %s length %s",
            digest,
            size,
            extra={"request_id": request_id, "user_id": user_id},
        )
        existing = await files.find_active_by_hash(user_id, digest)
        if existing is not None:
            raise ApiError(
                409,
                "duplicate_file",
                "A file with the same content already exists",
                {"file_id": existing["file_id"]},
            )
        file_id = str(uuid.uuid4())
        document = new_file_document(
            file_id=file_id,
            user_id=user_id,
            file_name=file_name,
            safe=safe_name(file_name),
            file_size=size,
            content_sha256=digest,
        )
        try:
            await objects.put(document["s3_key"], spool, size)
        except StorageError as exc:
            raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
        try:
            await files.insert(document)
        except DuplicateActiveFile as dup:
            await _delete_quiet(objects, document["s3_key"], file_id, user_id)
            raise ApiError(
                409,
                "duplicate_file",
                "A file with the same content already exists",
                {"file_id": dup.file_id},
            ) from dup
        except StorageError as exc:
            await _delete_quiet(objects, document["s3_key"], file_id, user_id)
            raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc

        created_at = utcnow()
        routing_key, body, properties = process_publication(
            message_id=str(uuid.uuid4()),
            file_id=file_id,
            user_id=user_id,
            s3_key=document["s3_key"],
            file_name=file_name,
            created_at=created_at,
            request_id=request_id,
            timestamp=int(created_at.timestamp()),
        )
        try:
            await publisher.publish(routing_key, body, properties)
        except PublishError as exc:
            try:
                await files.mark_enqueue_failed(file_id, user_id)
            except StorageError:
                logger.error(
                    "failed to record enqueue_failed",
                    extra={"request_id": request_id, "file_id": file_id, "user_id": user_id},
                )
            raise ApiError(500, "enqueue_failed", "Failed to publish message") from exc
        logger.info(
            "file uploaded",
            extra={"request_id": request_id, "file_id": file_id, "user_id": user_id},
        )
        return file_card(document)
    finally:
        if spool is not None:
            spool.close()
        if form is not None:
            await form.close()


async def list_pdfs(*, files, user_id: str, limit: int, offset: int) -> dict:
    items, total = await files.list_files(user_id, limit, offset)
    return {
        "items": [file_card(item) for item in items],
        "limit": limit,
        "offset": offset,
        "total": total,
    }


async def get_pdf(*, files, user_id: str, file_id: str) -> dict:
    document = await _owned_visible(files, user_id, file_id)
    return file_card(document)


async def delete_pdf(
    *,
    files,
    publisher,
    settings: Settings,
    user_id: str,
    file_id: str,
    request_id: str,
) -> dict:
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") == "deleted":
        raise ApiError(404, "file_not_found", "File not found")
    outcome = await files.claim_for_deletion(
        file_id,
        user_id,
        settings.stale_processing_seconds,
    )
    if outcome == "missing":
        raise ApiError(404, "file_not_found", "File not found")
    if outcome != "ok":
        raise ApiError(409, "file_busy", "File cannot be deleted in its current state")
    created_at = utcnow()
    routing_key, body, properties = delete_publication(
        message_id=str(uuid.uuid4()),
        file_id=file_id,
        user_id=user_id,
        s3_key=document["s3_key"],
        created_at=created_at,
        request_id=request_id,
        timestamp=int(created_at.timestamp()),
    )
    try:
        await publisher.publish(routing_key, body, properties)
    except PublishError as exc:
        logger.error(
            "delete publish failed",
            extra={"request_id": request_id, "file_id": file_id, "user_id": user_id},
        )
        raise ApiError(500, "enqueue_failed", "Failed to publish message") from exc
    return {"file_id": file_id, "status": "deleting"}


async def read_pdf(*, files, objects, user_id: str, file_id: str) -> tuple[bytes, str, int]:
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") not in CONTENT_STATUSES:
        raise ApiError(404, "file_not_found", "File not found")
    try:
        payload = await objects.get(document["s3_key"])
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    return payload, content_disposition(document["file_name"]), int(document["file_size"])


async def _owned_visible(files, user_id: str, file_id: str) -> dict:
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") == "deleted":
        raise ApiError(404, "file_not_found", "File not found")
    return document


async def _parse_form(request: Request, limit: int):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        raise ApiError(400, "validation_error", "Invalid request", {"fields": ["file"]})
    try:
        return await request.form(max_files=5, max_fields=20, max_part_size=limit)
    except ApiError:
        raise
    except Exception as exc:
        if _is_too_large(exc):
            raise ApiError(413, "file_too_large", "File exceeds the size limit") from exc
        raise ApiError(400, "validation_error", "Invalid request", {"fields": ["file"]}) from exc


def _is_too_large(exc: Exception) -> bool:
    text = str(exc).lower()
    return "maximum size" in text or "too large" in text or "exceeded" in text


async def _read_limited(upload: UploadFile, limit: int):
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
    total = 0
    try:
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            if total + len(chunk) > limit:
                raise ApiError(413, "file_too_large", "File exceeds the size limit")
            spool.write(chunk)
            total += len(chunk)
    except Exception:
        spool.close()
        raise
    spool.seek(0)
    return spool, total


def _is_pdf(stream: BinaryIO) -> bool:
    header = stream.read(5)
    stream.seek(0)
    return header.startswith(b"%PDF")


def _sha256(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


async def _delete_quiet(objects, key: str, file_id: str, user_id: str) -> None:
    try:
        await objects.delete(key)
    except StorageError:
        logger.error(
            "failed to delete object after metadata write failed",
            extra={"file_id": file_id, "user_id": user_id},
        )
