import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pika

from deletion_worker.errors import PublishError
from deletion_worker.messages import APP_ID, build_delete_payload
from deletion_worker.model import FileRecord
from deletion_worker.topology import DELETE_ROUTING_KEY


class RabbitDeletePublisher:
    def __init__(self, channel: Any, exchange: str) -> None:
        self._channel = channel
        self._exchange = exchange
        self._channel.confirm_delivery()

    def publish_delete(self, file: FileRecord, *, now: datetime | None = None) -> str:
        created_at = now or datetime.now(UTC)
        message_id = str(uuid.uuid4())
        payload = build_delete_payload(file, message_id, created_at)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_id = str(uuid.uuid4())
        properties = pika.BasicProperties(
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=2,
            message_id=message_id,
            timestamp=int(created_at.timestamp()),
            app_id=APP_ID,
            headers={"x-request-id": request_id},
        )
        try:
            confirmed = self._channel.basic_publish(
                exchange=self._exchange,
                routing_key=DELETE_ROUTING_KEY,
                body=body,
                properties=properties,
                mandatory=True,
            )
        except Exception as exc:
            raise PublishError("publish_not_confirmed") from exc
        if confirmed is False:
            raise PublishError("publish_not_confirmed")
        return message_id
