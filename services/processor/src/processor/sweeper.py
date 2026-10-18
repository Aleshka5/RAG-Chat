from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pika

from processor.logging import get_logger
from processor.messages import build_process_message
from processor.timeutil import format_z
from processor.topology import ROUTING_PROCESS


def process_properties(
    message_id: str,
    request_id: str | None,
    *,
    timestamp: int | None = None,
) -> pika.BasicProperties:
    headers = {"x-request-id": request_id} if request_id else None
    return pika.BasicProperties(
        content_type="application/json",
        content_encoding="utf-8",
        delivery_mode=2,
        message_id=message_id,
        timestamp=int(time.time()) if timestamp is None else timestamp,
        app_id="processor",
        headers=headers,
    )


class PikaProcessPublisher:
    def __init__(self, channel: Any, exchange: str) -> None:
        self._channel = channel
        self._exchange = exchange

    def publish_doc_process(self, body: dict[str, Any], message_id: str, request_id: str) -> None:
        self._channel.basic_publish(
            exchange=self._exchange,
            routing_key=ROUTING_PROCESS,
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            properties=process_properties(message_id, request_id),
            mandatory=False,
        )


def sweep_enqueue_failed(
    store: Any,
    publisher: Any,
    *,
    now: datetime,
    older_than_seconds: int,
    new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> int:
    """Republish doc.process for stale error=enqueue_failed files. Other errors stay put."""
    threshold = now - timedelta(seconds=older_than_seconds)
    published = 0
    for file_doc in store.find_enqueue_failed(threshold):
        message_id = new_id()
        request_id = new_id()
        body = build_process_message(file_doc, message_id, format_z(now))
        try:
            publisher.publish_doc_process(body, message_id, request_id)
        except Exception:
            get_logger().error(
                "sweep publish failed",
                extra={"file_id": file_doc.get("file_id"), "message_id": message_id},
            )
            continue
        published += 1
        get_logger().info(
            "sweep published doc.process",
            extra={"file_id": file_doc.get("file_id"), "message_id": message_id},
        )
    return published
