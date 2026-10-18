from __future__ import annotations

from typing import Any, Protocol

EXCHANGE_TYPE = "direct"
QUEUE_PROCESSING = "doc.processing"
QUEUE_DELETION = "doc.deletion"
QUEUE_PROCESSING_DEAD = "doc.processing.dead"
QUEUE_DELETION_DEAD = "doc.deletion.dead"
ROUTING_PROCESS = "doc.process"
ROUTING_DELETE = "doc.delete"


class _Channel(Protocol):
    def exchange_declare(
        self,
        exchange: str,
        exchange_type: str,
        durable: bool = False,
        **kwargs: Any,
    ) -> Any: ...

    def queue_declare(self, queue: str, durable: bool = False, arguments: dict | None = None, **kwargs: Any) -> Any: ...

    def queue_bind(self, queue: str, exchange: str, routing_key: str, **kwargs: Any) -> Any: ...


def processing_queue_arguments(dlx: str) -> dict[str, str]:
    return {
        "x-dead-letter-exchange": dlx,
        "x-dead-letter-routing-key": QUEUE_PROCESSING_DEAD,
    }


def deletion_queue_arguments(dlx: str) -> dict[str, str]:
    return {
        "x-dead-letter-exchange": dlx,
        "x-dead-letter-routing-key": QUEUE_DELETION_DEAD,
    }


def declare_topology(channel: _Channel, exchange: str, dlx: str) -> None:
    """Idempotent declare of the doc_events topology from messaging.md."""
    channel.exchange_declare(exchange=exchange, exchange_type=EXCHANGE_TYPE, durable=True)
    channel.exchange_declare(exchange=dlx, exchange_type=EXCHANGE_TYPE, durable=True)
    channel.queue_declare(
        queue=QUEUE_PROCESSING,
        durable=True,
        arguments=processing_queue_arguments(dlx),
    )
    channel.queue_declare(
        queue=QUEUE_DELETION,
        durable=True,
        arguments=deletion_queue_arguments(dlx),
    )
    channel.queue_declare(queue=QUEUE_PROCESSING_DEAD, durable=True)
    channel.queue_declare(queue=QUEUE_DELETION_DEAD, durable=True)
    channel.queue_bind(queue=QUEUE_PROCESSING, exchange=exchange, routing_key=ROUTING_PROCESS)
    channel.queue_bind(queue=QUEUE_DELETION, exchange=exchange, routing_key=ROUTING_DELETE)
    channel.queue_bind(queue=QUEUE_PROCESSING_DEAD, exchange=dlx, routing_key=QUEUE_PROCESSING_DEAD)
    channel.queue_bind(queue=QUEUE_DELETION_DEAD, exchange=dlx, routing_key=QUEUE_DELETION_DEAD)
