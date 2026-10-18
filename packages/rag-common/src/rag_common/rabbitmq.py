"""RabbitMQ topology and publish properties from docs/messaging.md.

Declaration is idempotent: the same exchange, queue, and binding arguments
are issued again. The broker accepts a repeat when the arguments match.
Queues have no priority argument. Consumers use ``prefetch_count=1``.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from rag_common.config import DEFAULTS
from rag_common.messages import DocDelete, DocProcess
from rag_common.request_id import amqp_headers

EXCHANGE = DEFAULTS["RABBITMQ_EXCHANGE"]
DEAD_LETTER_EXCHANGE = DEFAULTS["RABBITMQ_DLX"]

QUEUE_PROCESSING = "doc.processing"
QUEUE_DELETION = "doc.deletion"
QUEUE_PROCESSING_DEAD = "doc.processing.dead"
QUEUE_DELETION_DEAD = "doc.deletion.dead"

ROUTING_PROCESS = "doc.process"
ROUTING_DELETE = "doc.delete"

PREFETCH_COUNT = 1

APP_IDS = frozenset({"file-collector", "processor", "deletion-worker"})

CONTENT_TYPE = "application/json"
CONTENT_ENCODING = "utf-8"
DELIVERY_MODE = 2


@dataclass(frozen=True)
class ExchangeSpec:
    name: str
    exchange_type: str
    durable: bool


@dataclass(frozen=True)
class QueueSpec:
    name: str
    durable: bool
    arguments: dict[str, str]
    bindings: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Topology:
    exchanges: tuple[ExchangeSpec, ...]
    queues: tuple[QueueSpec, ...]


@dataclass(frozen=True)
class PublishSpec:
    routing_key: str
    body: bytes
    content_type: str
    content_encoding: str
    delivery_mode: int
    message_id: str
    timestamp: int
    app_id: str
    headers: dict[str, str]


def rabbitmq_topology(
    exchange: str = EXCHANGE,
    dead_letter_exchange: str = DEAD_LETTER_EXCHANGE,
) -> Topology:
    return Topology(
        exchanges=(
            ExchangeSpec(exchange, "direct", True),
            ExchangeSpec(dead_letter_exchange, "direct", True),
        ),
        queues=(
            QueueSpec(
                QUEUE_PROCESSING,
                True,
                {
                    "x-dead-letter-exchange": dead_letter_exchange,
                    "x-dead-letter-routing-key": QUEUE_PROCESSING_DEAD,
                },
                ((exchange, ROUTING_PROCESS),),
            ),
            QueueSpec(
                QUEUE_DELETION,
                True,
                {
                    "x-dead-letter-exchange": dead_letter_exchange,
                    "x-dead-letter-routing-key": QUEUE_DELETION_DEAD,
                },
                ((exchange, ROUTING_DELETE),),
            ),
            QueueSpec(
                QUEUE_PROCESSING_DEAD,
                True,
                {},
                ((dead_letter_exchange, QUEUE_PROCESSING_DEAD),),
            ),
            QueueSpec(
                QUEUE_DELETION_DEAD,
                True,
                {},
                ((dead_letter_exchange, QUEUE_DELETION_DEAD),),
            ),
        ),
    )


class Channel(Protocol):
    def exchange_declare(self, *, exchange: str, exchange_type: str, durable: bool) -> Any: ...

    def queue_declare(
        self,
        *,
        queue: str,
        durable: bool,
        arguments: dict[str, str] | None = None,
    ) -> Any: ...

    def queue_bind(self, *, queue: str, exchange: str, routing_key: str) -> Any: ...

    def basic_qos(self, *, prefetch_count: int) -> Any: ...


def declare_topology(
    channel: Channel,
    *,
    exchange: str = EXCHANGE,
    dead_letter_exchange: str = DEAD_LETTER_EXCHANGE,
) -> None:
    """Declare the direct exchanges, durable queues, and bindings."""
    topology = rabbitmq_topology(exchange, dead_letter_exchange)
    for item in topology.exchanges:
        channel.exchange_declare(
            exchange=item.name,
            exchange_type=item.exchange_type,
            durable=item.durable,
        )
    for queue in topology.queues:
        if queue.arguments:
            channel.queue_declare(
                queue=queue.name,
                durable=queue.durable,
                arguments=queue.arguments,
            )
        else:
            channel.queue_declare(queue=queue.name, durable=queue.durable)
        for bound_exchange, routing_key in queue.bindings:
            channel.queue_bind(queue=queue.name, exchange=bound_exchange, routing_key=routing_key)


def apply_prefetch(channel: Channel) -> None:
    """One unacked message per consumer channel."""
    channel.basic_qos(prefetch_count=PREFETCH_COUNT)


def build_publish(
    message: DocProcess | DocDelete,
    *,
    app_id: str,
    timestamp: int,
    request_id: str | None = None,
) -> PublishSpec:
    """Properties for a confirmed publish. The body never contains ``x-death``.

    The caller waits for publisher confirm. A nack from the broker is a publish failure.
    """
    if app_id not in APP_IDS:
        raise ValueError("app_id must be file-collector, processor, or deletion-worker")
    if type(timestamp) is not int:
        raise ValueError("timestamp must be a Unix time integer")
    payload = message.model_dump()
    if "x-death" in payload:
        raise ValueError("x-death must not be placed in the body")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return PublishSpec(
        routing_key=str(message.message_type),
        body=body,
        content_type=CONTENT_TYPE,
        content_encoding=CONTENT_ENCODING,
        delivery_mode=DELIVERY_MODE,
        message_id=str(message.message_id),
        timestamp=timestamp,
        app_id=app_id,
        headers=amqp_headers(request_id),
    )
