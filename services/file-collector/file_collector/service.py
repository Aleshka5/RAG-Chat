"""Upload, list, content, delete, and re-key use cases."""

import hashlib
import json
import logging
import re
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
    ObjectNotFound,
    PublishError,
    StorageError,
)
from file_collector.messages import delete_publication, process_publication
from file_collector.names import content_disposition, safe_name, validated_file_name
from file_collector.schema import CONTENT_STATUSES, deletion_allowed, file_card, new_file_document

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCUMENT_CONTENT_TYPES = frozenset({PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE, XLSX_CONTENT_TYPE})
IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEY_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_FILES_PREFIX = re.compile(rf"^files/({_KEY_UUID})/")
_RAG_FILES_PREFIX = re.compile(rf"^rag/files/({_KEY_UUID})/")
_USERS_PREFIX = re.compile(rf"^users/({_KEY_UUID})/")
_STORAGE_PREFIXES = ("users/", "_meta/", "shared/")
_ORIGINS = frozenset({"rag", "storage"})

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
    return await _accept_upload(
        request=request,
        user_id=user_id,
        request_id=request_id,
        settings=settings,
        files=files,
        objects=objects,
        publisher=publisher,
        detect=_pdf_content_type,
        pdf_extension=True,
        unsupported_message="Only PDF is accepted",
    )


async def upload_image(
    *,
    request: Request,
    user_id: str,
    request_id: str,
    settings: Settings,
    files,
    objects,
    publisher,
) -> dict:
    """Multipart image intake. The bytes decide the type, not the declared one."""
    return await _accept_upload(
        request=request,
        user_id=user_id,
        request_id=request_id,
        settings=settings,
        files=files,
        objects=objects,
        publisher=publisher,
        detect=_image_content_type,
        pdf_extension=False,
        unsupported_message="Only JPEG, PNG, WebP and GIF images are accepted",
    )


async def _accept_upload(
    *,
    request: Request,
    user_id: str,
    request_id: str,
    settings: Settings,
    files,
    objects,
    publisher,
    detect,
    pdf_extension: bool,
    unsupported_message: str,
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
        content_type = detect(spool)
        if content_type is None:
            raise ApiError(415, "unsupported_media_type", unsupported_message)
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
            safe=safe_name(file_name, pdf_extension=pdf_extension),
            file_size=size,
            content_sha256=digest,
            content_type=content_type,
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
            content_type=content_type,
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


async def accept_manifest(
    *,
    request: Request,
    user_id: str,
    request_id: str,
    files,
    objects,
    publisher,
    allowed_types: frozenset[str],
) -> dict:
    """Register an object that is already in the bucket. Bytes are not copied."""
    payload = await _read_manifest(request)
    manifest = _validated_manifest(payload, allowed_types)
    s3_key = manifest["s3_key"]
    if _rejects_manifest_key(s3_key, user_id, manifest["origin"]):
        raise ApiError(404, "object_not_found", "Object not found")
    try:
        reported_size = await objects.head(s3_key)
    except ObjectNotFound as exc:
        raise ApiError(404, "object_not_found", "Object not found") from exc
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    if (
        isinstance(reported_size, int)
        and not isinstance(reported_size, bool)
        and reported_size != manifest["file_size"]
    ):
        raise ApiError(
            400,
            "validation_error",
            "Invalid request",
            {"fields": ["file_size"]},
        )
    file_name = manifest["file_name"]
    digest = manifest["content_sha256"]
    content_type = manifest["content_type"]
    pdf_extension = content_type == PDF_CONTENT_TYPE
    logger.debug(
        "manifest sha256 %s length %s",
        digest,
        manifest["file_size"],
        extra={"request_id": request_id, "user_id": user_id},
    )
    existing = await _active_duplicate(files, user_id, digest, s3_key)
    if existing is not None:
        raise _duplicate(existing["file_id"])
    file_id = str(uuid.uuid4())
    document = new_file_document(
        file_id=file_id,
        user_id=user_id,
        file_name=file_name,
        safe=safe_name(file_name, pdf_extension=pdf_extension),
        file_size=manifest["file_size"],
        content_sha256=digest,
        content_type=content_type,
        s3_key=s3_key,
        object_owner=manifest["origin"],
    )
    try:
        await files.insert(document)
    except DuplicateActiveFile as dup:
        raise _duplicate(dup.file_id) from dup
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    await _publish_process(
        files=files,
        publisher=publisher,
        document=document,
        file_name=file_name,
        content_type=content_type,
        request_id=request_id,
    )
    logger.info(
        "file uploaded",
        extra={"request_id": request_id, "file_id": file_id, "user_id": user_id},
    )
    return file_card(document)


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


async def rekey_object(
    *,
    request: Request,
    user_id: str,
    file_id: str,
    request_id: str,
    settings: Settings,
    files,
    objects,
    publisher,
) -> dict:
    """Point an existing file at a new key and publish ``doc.process`` again."""
    payload = await _read_manifest(request)
    body = _validated_rekey(payload)
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") in {"deleted", "deleting"}:
        raise ApiError(404, "file_not_found", "File not found")
    digest = body["content_sha256"]
    if document.get("content_sha256") != digest:
        raise ApiError(409, "content_changed", "Content hash does not match the stored file")
    new_key = body["s3_key"]
    same_key = document.get("s3_key") == new_key
    now = utcnow()
    if not same_key and _new_key_is_busy(document, now, settings.stale_processing_seconds):
        raise ApiError(409, "file_busy", "File cannot be updated in its current state")
    owner = document.get("object_owner")
    if owner != "storage":
        owner = "rag"
    if _rejects_manifest_key(new_key, user_id, owner):
        raise ApiError(404, "object_not_found", "Object not found")
    try:
        reported_size = await objects.head(new_key)
    except ObjectNotFound as exc:
        raise ApiError(404, "object_not_found", "Object not found") from exc
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    if (
        isinstance(reported_size, int)
        and not isinstance(reported_size, bool)
        and reported_size != body["file_size"]
    ):
        raise ApiError(
            400,
            "validation_error",
            "Invalid request",
            {"fields": ["file_size"]},
        )
    existing = await files.find_active_by_s3_key(user_id, new_key)
    if existing is not None and existing["file_id"] != file_id:
        raise _duplicate(existing["file_id"])
    try:
        updated = await files.rekey(
            file_id,
            user_id,
            observed_key=document["s3_key"],
            new_key=new_key,
            content_sha256=digest,
            same_key=same_key,
            now=now,
            stale_seconds=settings.stale_processing_seconds,
        )
    except DuplicateActiveFile as dup:
        raise _duplicate(dup.file_id) from dup
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    if updated is None:
        raise ApiError(409, "file_busy", "File cannot be updated in its current state")
    content_type = updated.get("content_type") or "application/pdf"
    if not isinstance(content_type, str) or content_type == "":
        content_type = "application/pdf"
    await _publish_process(
        files=files,
        publisher=publisher,
        document=updated,
        file_name=updated["file_name"],
        content_type=content_type,
        request_id=request_id,
    )
    logger.info(
        "file rekeyed",
        extra={"request_id": request_id, "file_id": file_id, "user_id": user_id},
    )
    return file_card(updated)


def _new_key_is_busy(document: dict, now, stale_seconds: int) -> bool:
    status = document.get("status")
    if status in {"ready", "error"}:
        return False
    if status == "processing":
        return not deletion_allowed("processing", document["updated_at"], now, stale_seconds)
    return True


async def read_pdf(
    *,
    files,
    objects,
    user_id: str,
    file_id: str,
) -> tuple[bytes, str, int, str]:
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") not in CONTENT_STATUSES:
        raise ApiError(404, "file_not_found", "File not found")
    try:
        payload = await objects.get(document["s3_key"])
    except StorageError as exc:
        raise ApiError(503, "dependency_unavailable", "Dependency unavailable") from exc
    media_type = document.get("content_type") or "application/pdf"
    if not isinstance(media_type, str) or media_type == "":
        media_type = "application/pdf"
    return (
        payload,
        content_disposition(document["file_name"]),
        int(document["file_size"]),
        media_type,
    )


async def _owned_visible(files, user_id: str, file_id: str) -> dict:
    document = await files.get(file_id, user_id)
    if document is None or document.get("status") == "deleted":
        raise ApiError(404, "file_not_found", "File not found")
    return document


async def _publish_process(
    *,
    files,
    publisher,
    document: dict,
    file_name: str,
    content_type: str,
    request_id: str,
) -> None:
    file_id = document["file_id"]
    user_id = document["user_id"]
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
        content_type=content_type,
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


async def _active_duplicate(files, user_id: str, digest: str, s3_key: str) -> dict | None:
    by_key = await files.find_active_by_s3_key(user_id, s3_key)
    if by_key is not None:
        return by_key
    return await files.find_active_by_hash(user_id, digest)


def _duplicate(file_id: str) -> ApiError:
    return ApiError(
        409,
        "duplicate_file",
        "A file with the same content already exists",
        {"file_id": file_id},
    )


async def _read_manifest(request: Request) -> dict:
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "validation_error", "Invalid request") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "validation_error", "Invalid request")
    return payload


def _validated_manifest(payload: dict, allowed_types: frozenset[str]) -> dict:
    fields: list[str] = []
    s3_key = payload.get("s3_key")
    if not _valid_s3_key(s3_key):
        fields.append("s3_key")
    file_name = None
    raw_name = payload.get("file_name")
    if not isinstance(raw_name, str):
        fields.append("file_name")
    else:
        try:
            file_name = validated_file_name(raw_name)
        except ValueError:
            fields.append("file_name")
    digest = payload.get("content_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        fields.append("content_sha256")
    file_size = payload.get("file_size")
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 1:
        fields.append("file_size")
    content_type = payload.get("content_type")
    if not isinstance(content_type, str):
        fields.append("content_type")
    origin = _manifest_origin(payload, fields)
    if fields:
        raise ApiError(400, "validation_error", "Invalid request", {"fields": fields})
    if content_type not in allowed_types:
        raise ApiError(415, "unsupported_media_type", _unsupported_media_message(allowed_types))
    return {
        "s3_key": s3_key,
        "file_name": file_name,
        "content_sha256": digest,
        "file_size": file_size,
        "content_type": content_type,
        "origin": origin,
    }


def _validated_rekey(payload: dict) -> dict:
    fields: list[str] = []
    s3_key = payload.get("s3_key")
    if not _valid_s3_key(s3_key):
        fields.append("s3_key")
    file_size = payload.get("file_size")
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 1:
        fields.append("file_size")
    digest = payload.get("content_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        fields.append("content_sha256")
    if fields:
        raise ApiError(400, "validation_error", "Invalid request", {"fields": fields})
    return {"s3_key": s3_key, "file_size": file_size, "content_sha256": digest}


def _unsupported_media_message(allowed_types: frozenset[str]) -> str:
    if allowed_types == IMAGE_CONTENT_TYPES:
        return "Only JPEG, PNG, WEBP, and GIF are accepted"
    if allowed_types == DOCUMENT_CONTENT_TYPES:
        return "Only PDF, DOCX, and XLSX are accepted"
    return "Only PDF is accepted"


def _manifest_origin(payload: dict, fields: list[str]) -> str:
    if "origin" not in payload:
        return "rag"
    origin = payload["origin"]
    if origin not in _ORIGINS:
        fields.append("origin")
        return "rag"
    return origin


def _valid_s3_key(value: object) -> bool:
    if not isinstance(value, str) or value == "":
        return False
    return not (value.startswith("/") or "\\" in value or ".." in value)


def _rejects_manifest_key(s3_key: str, user_id: str, origin: str) -> bool:
    if origin == "storage":
        match = _USERS_PREFIX.match(s3_key)
        return match is None or match.group(1).lower() != user_id
    if s3_key.startswith(_STORAGE_PREFIXES):
        return True
    for pattern in (_FILES_PREFIX, _RAG_FILES_PREFIX):
        match = pattern.match(s3_key)
        if match is not None and match.group(1).lower() != user_id:
            return True
    return False


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


def _pdf_content_type(stream: BinaryIO) -> str | None:
    header = stream.read(5)
    stream.seek(0)
    if header.startswith(b"%PDF"):
        return PDF_CONTENT_TYPE
    return None


def _image_content_type(stream: BinaryIO) -> str | None:
    """Detect one of the four accepted image types by its magic bytes."""
    header = stream.read(16)
    stream.seek(0)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return None


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
