"""File document shape, indexes, and API cards."""

from datetime import datetime, timedelta

from file_collector.clock import to_iso, utcnow

ACTIVE_STATUSES = ("uploaded", "processing", "ready", "error", "deleting")
DELETABLE_STATUSES = ("uploaded", "ready", "error")
CONTENT_STATUSES = ("uploaded", "processing", "ready", "error")


def file_indexes() -> list[dict]:
    return [
        {"keys": [("file_id", 1)], "unique": True},
        {"keys": [("user_id", 1), ("status", 1)], "unique": False},
        {"keys": [("user_id", 1), ("created_at", -1)], "unique": False},
        {
            "keys": [("user_id", 1), ("content_sha256", 1)],
            "unique": True,
            "partialFilterExpression": {"status": {"$in": list(ACTIVE_STATUSES)}},
        },
    ]


def new_file_document(
    *,
    file_id: str,
    user_id: str,
    file_name: str,
    safe: str,
    file_size: int,
    content_sha256: str,
    now: datetime | None = None,
) -> dict:
    moment = now or utcnow()
    return {
        "file_id": file_id,
        "user_id": user_id,
        "file_name": file_name,
        "safe_name": safe,
        "file_size": file_size,
        "content_type": "application/pdf",
        "content_sha256": content_sha256,
        "s3_key": f"files/{user_id}/{file_id}/{safe}",
        "status": "uploaded",
        "page_count": None,
        "error": None,
        "delete_claimed_at": None,
        "created_at": moment,
        "updated_at": moment,
    }


def deletion_claim_filter(file_id: str, user_id: str, stale_before: datetime) -> dict:
    return {
        "file_id": file_id,
        "user_id": user_id,
        "$or": [
            {"status": {"$in": list(DELETABLE_STATUSES)}},
            {"status": "processing", "updated_at": {"$lt": stale_before}},
        ],
    }


def deletion_allowed(status: str, updated_at: datetime, now: datetime, stale_seconds: int) -> bool:
    if status in DELETABLE_STATUSES:
        return True
    if status == "processing":
        moment = updated_at
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=now.tzinfo)
        return moment < now - timedelta(seconds=stale_seconds)
    return False


def file_card(document: dict) -> dict:
    status = document["status"]
    progress = None
    if status == "processing":
        checkpoint = document.get("checkpoint") or {}
        progress = {
            "pages_done": _count(checkpoint.get("pages_done")),
            "pages_total": checkpoint.get("pages_total"),
            "chunks_done": _count(checkpoint.get("chunks_done")),
            "chunks_total": checkpoint.get("chunks_total"),
        }
    return {
        "file_id": document["file_id"],
        "file_name": document["file_name"],
        "file_size": document["file_size"],
        "status": status,
        "page_count": document.get("page_count"),
        "error": document.get("error"),
        "progress": progress,
        "created_at": to_iso(document["created_at"]),
        "updated_at": to_iso(document["updated_at"]),
    }


def _count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
