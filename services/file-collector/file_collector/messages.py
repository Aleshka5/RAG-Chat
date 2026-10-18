"""RabbitMQ topology and publication bodies."""

from datetime import datetime

from file_collector.clock import to_iso

PROCESS_ROUTING_KEY = "doc.process"
DELETE_ROUTING_KEY = "doc.delete"
PROCESSING_QUEUE = "doc.processing"
DELETION_QUEUE = "doc.deletion"
PROCESSING_DEAD = "doc.processing.dead"
DELETION_DEAD = "doc.deletion.dead"
APP_ID = "file-collector"


def topology(exchange: str, dlx: str) -> dict:
    return {
        "exchanges": [
            {"name": exchange, "type": "direct", "durable": True},
            {"name": dlx, "type": "direct", "durable": True},
        ],
        "queues": [
            {
                "name": PROCESSING_QUEUE,
                "durable": True,
                "arguments": {
                    "x-dead-letter-exchange": dlx,
                    "x-dead-letter-routing-key": PROCESSING_DEAD,
                },
            },
            {
                "name": DELETION_QUEUE,
                "durable": True,
                "arguments": {
                    "x-dead-letter-exchange": dlx,
                    "x-dead-letter-routing-key": DELETION_DEAD,
                },
            },
            {"name": PROCESSING_DEAD, "durable": True, "arguments": {}},
            {"name": DELETION_DEAD, "durable": True, "arguments": {}},
        ],
        "bindings": [
            {"queue": PROCESSING_QUEUE, "exchange": exchange, "routing_key": PROCESS_ROUTING_KEY},
            {"queue": DELETION_QUEUE, "exchange": exchange, "routing_key": DELETE_ROUTING_KEY},
            {"queue": PROCESSING_DEAD, "exchange": dlx, "routing_key": PROCESSING_DEAD},
            {"queue": DELETION_DEAD, "exchange": dlx, "routing_key": DELETION_DEAD},
        ],
    }


def process_publication(
    *,
    message_id: str,
    file_id: str,
    user_id: str,
    s3_key: str,
    file_name: str,
    created_at: datetime,
    request_id: str | None,
    timestamp: int,
) -> tuple[str, dict, dict]:
    body = {
        "schema_version": 1,
        "message_type": "doc.process",
        "message_id": message_id,
        "file_id": file_id,
        "user_id": user_id,
        "s3_key": s3_key,
        "file_name": file_name,
        "content_type": "application/pdf",
        "created_at": to_iso(created_at),
    }
    return PROCESS_ROUTING_KEY, body, _properties(message_id, request_id, timestamp)


def delete_publication(
    *,
    message_id: str,
    file_id: str,
    user_id: str,
    s3_key: str,
    created_at: datetime,
    request_id: str | None,
    timestamp: int,
) -> tuple[str, dict, dict]:
    body = {
        "schema_version": 1,
        "message_type": "doc.delete",
        "message_id": message_id,
        "file_id": file_id,
        "user_id": user_id,
        "s3_key": s3_key,
        "created_at": to_iso(created_at),
    }
    return DELETE_ROUTING_KEY, body, _properties(message_id, request_id, timestamp)


def _properties(message_id: str, request_id: str | None, timestamp: int) -> dict:
    headers: dict[str, str] = {}
    if request_id:
        headers["x-request-id"] = request_id
    return {
        "content_type": "application/json",
        "content_encoding": "utf-8",
        "delivery_mode": 2,
        "message_id": message_id,
        "timestamp": timestamp,
        "app_id": APP_ID,
        "headers": headers,
    }
