import logging
from collections.abc import Callable
from typing import Any

from deletion_worker.handler import DeletionHandler
from deletion_worker.log import log_fields
from deletion_worker.model import Outcome

logger = logging.getLogger("deletion_worker")


def request_id_from_headers(properties: Any) -> str | None:
    headers = getattr(properties, "headers", None)
    if not isinstance(headers, dict):
        return None
    value = headers.get("x-request-id")
    if isinstance(value, str) and value:
        return value
    return None


def handle_delivery(
    channel: Any,
    method: Any,
    properties: Any,
    body: bytes,
    handler: DeletionHandler,
    on_crash: Callable[[], None],
) -> None:
    request_id = request_id_from_headers(properties)
    try:
        outcome = handler.handle(body, request_id=request_id)
    except Exception:
        logger.exception(
            "delete delivery crashed; leaving the message unacked for redelivery",
            extra=log_fields(request_id=request_id),
        )
        on_crash()
        return
    delivery_tag = method.delivery_tag
    try:
        if outcome is Outcome.ACK:
            channel.basic_ack(delivery_tag=delivery_tag)
        else:
            channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
    except Exception:
        logger.exception(
            "broker ack failed; leaving the message unacked for redelivery",
            extra=log_fields(request_id=request_id),
        )
        on_crash()
