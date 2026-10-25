import logging
import signal
from typing import Any

import pika

from deletion_worker.config import Settings
from deletion_worker.delivery import handle_delivery
from deletion_worker.handler import DeletionHandler
from deletion_worker.log import log_fields
from deletion_worker.mongo_store import MongoFileStore, connect_mongo
from deletion_worker.object_store import S3ObjectStore, connect_s3
from deletion_worker.publisher import RabbitDeletePublisher
from deletion_worker.sweeper import Sweeper
from deletion_worker.topology import declare_topology, register_consumer
from deletion_worker.vector_store import QdrantVectorStore, connect_qdrant

logger = logging.getLogger("deletion_worker")


class DeletionService:
    def __init__(
        self,
        settings: Settings,
        connection: Any,
        files: MongoFileStore,
        handler: DeletionHandler,
        sweeper: Sweeper,
    ) -> None:
        self._settings = settings
        self._connection = connection
        self._files = files
        self._handler = handler
        self._sweeper = sweeper
        self._stop = False

    def run(self) -> None:
        self._files.ensure_indexes()
        setup = self._connection.channel()
        declare_topology(setup, self._settings.rabbitmq_exchange, self._settings.rabbitmq_dlx)
        self._sweeper.run_once()
        for _ in range(self._settings.deletion_concurrency):
            channel = self._connection.channel()
            register_consumer(channel, self._on_message)
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        logger.info(
            "deletion worker consuming",
            extra=log_fields(reason="ready"),
        )
        while not self._stop:
            self._connection.process_data_events(time_limit=self._settings.sweep_interval_seconds)
            if self._stop:
                break
            self._sweeper.run_once()
        self._close()

    def _on_message(self, channel: Any, method: Any, properties: Any, body: bytes) -> None:
        handle_delivery(channel, method, properties, body, self._handler, self._crash)

    def _crash(self) -> None:
        self._stop = True
        self._close()

    def _request_stop(self, _signum: int, _frame: object) -> None:
        self._stop = True

    def _close(self) -> None:
        try:
            if getattr(self._connection, "is_open", True):
                self._connection.close()
        except Exception:
            logger.warning("rabbitmq connection close failed", extra=log_fields(reason="rabbitmq"))


def build_service(settings: Settings) -> DeletionService:
    mongo = connect_mongo(settings.mongodb_uri)
    files = MongoFileStore(mongo)
    objects = S3ObjectStore(
        connect_s3(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_region,
        ),
        settings.s3_bucket,
    )
    vectors = QdrantVectorStore(
        connect_qdrant(settings.qdrant_url),
        settings.qdrant_collection,
        settings.qdrant_images_collection,
    )
    handler = DeletionHandler(
        files,
        objects,
        vectors,
        stale_processing_seconds=settings.stale_processing_seconds,
    )
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 60
    params.blocked_connection_timeout = 60
    connection = pika.BlockingConnection(params)
    publisher_channel = connection.channel()
    publisher = RabbitDeletePublisher(publisher_channel, settings.rabbitmq_exchange)
    sweeper = Sweeper(
        files,
        publisher,
        delete_requeue_after_seconds=settings.delete_requeue_after_seconds,
    )
    return DeletionService(settings, connection, files, handler, sweeper)
