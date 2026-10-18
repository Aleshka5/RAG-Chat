from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pika

from processor.pipeline import DeliveryResult
from processor.topology import QUEUE_PROCESSING

# One unacked message per channel. PROCESSOR_CONCURRENCY is the number of channels.
PREFETCH_COUNT = 1


def attach_consumer(channel: Any, callback: Callable[..., None]) -> None:
    channel.basic_qos(prefetch_count=PREFETCH_COUNT)
    channel.basic_consume(
        queue=QUEUE_PROCESSING,
        on_message_callback=callback,
        auto_ack=False,
    )


def attach_consumers(connection: Any, concurrency: int, callback: Callable[..., None]) -> list[Any]:
    channels = []
    for _ in range(concurrency):
        channel = connection.channel()
        attach_consumer(channel, callback)
        channels.append(channel)
    return channels


def settle(
    channel: Any,
    delivery_tag: int,
    result: DeliveryResult,
    *,
    sleeper: Callable[[float], None] | None = None,
) -> None:
    """Ack, or nack. A requeue sleeps first so prefetch=1 does not hot-loop."""
    if result.action == "nack" and result.requeue and result.delay_seconds > 0:
        if sleeper is None:
            time.sleep(result.delay_seconds)
        else:
            sleeper(result.delay_seconds)
    if result.action == "ack":
        channel.basic_ack(delivery_tag)
        return
    channel.basic_nack(delivery_tag, requeue=result.requeue)


def make_consumer(
    pipeline: Any,
    *,
    connection: Any | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Callable[..., None]:
    def on_message(channel: Any, method: Any, properties: Any, body: bytes) -> None:
        headers: dict[str, Any] = {}
        if properties is not None and getattr(properties, "headers", None):
            headers = dict(properties.headers)
        result = pipeline.handle(
            body,
            redelivered=bool(getattr(method, "redelivered", False)),
            headers=headers,
        )
        pause = sleeper
        if pause is None and connection is not None and result.requeue and result.delay_seconds > 0:

            def pause(seconds: float, connection: Any = connection) -> None:
                connection.sleep(seconds)

        settle(channel, method.delivery_tag, result, sleeper=pause)

    return on_message


def connect(rabbitmq_url: str) -> pika.BlockingConnection:
    parameters = pika.URLParameters(rabbitmq_url)
    parameters.heartbeat = 120
    parameters.blocked_connection_timeout = 120
    return pika.BlockingConnection(parameters)
