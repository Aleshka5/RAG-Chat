"""RabbitMQ publisher with confirms and idempotent topology."""

import json
import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType

from file_collector.config import Settings
from file_collector.errors import PublishError
from file_collector.messages import topology

logger = logging.getLogger("file_collector")


class RabbitPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection = None
        self._channel = None
        self._exchanges: dict = {}

    async def connect(self) -> None:
        try:
            self._connection = await aio_pika.connect_robust(
                self._settings.rabbitmq_url,
                timeout=10,
                fail_fast=True,
            )
            self._channel = await self._connection.channel(
                publisher_confirms=True,
                on_return_raises=True,
            )
        except Exception as exc:
            logger.error("rabbitmq connection failed %s", type(exc).__name__)
            raise PublishError(type(exc).__name__) from exc

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._channel = None
            self._exchanges = {}

    async def ensure_topology(self) -> None:
        channel = self._channel
        if channel is None:
            raise PublishError("rabbitmq")
        spec = topology(self._settings.rabbitmq_exchange, self._settings.rabbitmq_dlx)
        try:
            declared_queues = {}
            for exchange in spec["exchanges"]:
                declared = await channel.declare_exchange(
                    exchange["name"],
                    ExchangeType(exchange["type"]),
                    durable=exchange["durable"],
                )
                self._exchanges[exchange["name"]] = declared
            for queue_spec in spec["queues"]:
                arguments = queue_spec["arguments"] or None
                declared_queues[queue_spec["name"]] = await channel.declare_queue(
                    queue_spec["name"],
                    durable=queue_spec["durable"],
                    arguments=arguments,
                )
            for binding in spec["bindings"]:
                await declared_queues[binding["queue"]].bind(
                    self._exchanges[binding["exchange"]],
                    routing_key=binding["routing_key"],
                )
        except Exception as exc:
            logger.error("rabbitmq topology failed %s", type(exc).__name__)
            raise PublishError(type(exc).__name__) from exc

    async def publish(self, routing_key: str, body: dict, properties: dict) -> None:
        exchange = self._exchanges.get(self._settings.rabbitmq_exchange)
        if exchange is None:
            raise PublishError("rabbitmq")
        message = aio_pika.Message(
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            content_type=properties["content_type"],
            content_encoding=properties["content_encoding"],
            delivery_mode=DeliveryMode(properties["delivery_mode"]),
            message_id=properties["message_id"],
            timestamp=properties["timestamp"],
            app_id=properties["app_id"],
            headers=properties["headers"] or None,
        )
        try:
            confirmation = await exchange.publish(message, routing_key=routing_key)
            if confirmation is False:
                raise PublishError("nack")
        except PublishError:
            raise
        except Exception as exc:
            logger.error(
                "publish failed %s",
                type(exc).__name__,
                extra={
                    "message_id": properties.get("message_id"),
                    "file_id": body.get("file_id"),
                    "user_id": body.get("user_id"),
                },
            )
            raise PublishError(type(exc).__name__) from exc
