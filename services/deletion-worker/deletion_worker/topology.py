from collections.abc import Callable
from typing import Any

PROCESSING_QUEUE = "doc.processing"
DELETION_QUEUE = "doc.deletion"
PROCESSING_DEAD = "doc.processing.dead"
DELETION_DEAD = "doc.deletion.dead"
PROCESS_ROUTING_KEY = "doc.process"
DELETE_ROUTING_KEY = "doc.delete"


def declare_topology(channel: Any, exchange: str, dlx: str) -> None:
    """Declare the shared doc_events topology. Repeating the call is safe."""

    channel.exchange_declare(exchange=exchange, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=dlx, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=PROCESSING_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": dlx,
            "x-dead-letter-routing-key": PROCESSING_DEAD,
        },
    )
    channel.queue_declare(
        queue=DELETION_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": dlx,
            "x-dead-letter-routing-key": DELETION_DEAD,
        },
    )
    channel.queue_declare(queue=PROCESSING_DEAD, durable=True)
    channel.queue_declare(queue=DELETION_DEAD, durable=True)
    channel.queue_bind(queue=PROCESSING_QUEUE, exchange=exchange, routing_key=PROCESS_ROUTING_KEY)
    channel.queue_bind(queue=DELETION_QUEUE, exchange=exchange, routing_key=DELETE_ROUTING_KEY)
    channel.queue_bind(queue=PROCESSING_DEAD, exchange=dlx, routing_key=PROCESSING_DEAD)
    channel.queue_bind(queue=DELETION_DEAD, exchange=dlx, routing_key=DELETION_DEAD)


def register_consumer(channel: Any, callback: Callable[..., None]) -> None:
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(
        queue=DELETION_QUEUE,
        on_message_callback=callback,
        auto_ack=False,
    )
