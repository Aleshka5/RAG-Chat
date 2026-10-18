from __future__ import annotations

import signal
import time

from processor.config import load_settings
from processor.consumer import attach_consumers, connect, make_consumer
from processor.http_clients import EmbeddingClient, OcrClient
from processor.logging import get_logger, setup_logging
from processor.mongo_store import MongoFiles
from processor.pipeline import Pipeline
from processor.qdrant_store import QdrantStore
from processor.storage import ObjectStorage
from processor.sweeper import PikaProcessPublisher, sweep_enqueue_failed
from processor.timeutil import utcnow
from processor.tokenizer import load_tokenizer
from processor.topology import declare_topology


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    logger = get_logger()
    store = MongoFiles(settings)
    store.ensure_indexes()
    qdrant = QdrantStore(settings)
    qdrant.ensure_collection()
    blobs = ObjectStorage(settings)
    tokenizer = load_tokenizer(settings.embedding_model)
    ocr = OcrClient(
        settings.ocr_url,
        timeout=settings.ocr_timeout,
        max_attempts=settings.ocr_max_attempts,
    )
    embedding = EmbeddingClient(
        settings.embedding_url,
        timeout=settings.embedding_timeout,
        max_attempts=3,
        batch_size=settings.embedding_batch_size,
        dimension=settings.embedding_dim,
        model=settings.embedding_model,
    )
    pipeline = Pipeline(
        settings,
        store,
        blobs,
        ocr,
        embedding,
        qdrant,
        tokenizer,
    )
    connection = connect(settings.rabbitmq_url)
    setup = connection.channel()
    declare_topology(setup, settings.rabbitmq_exchange, settings.rabbitmq_dlx)
    publisher_channel = connection.channel()
    publisher_channel.confirm_delivery()
    publisher = PikaProcessPublisher(publisher_channel, settings.rabbitmq_exchange)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def run_sweep() -> None:
        try:
            sweep_enqueue_failed(
                store,
                publisher,
                now=utcnow(),
                older_than_seconds=settings.upload_requeue_after_seconds,
            )
        except Exception:
            logger.warning("sweep failed")

    callback = make_consumer(pipeline, connection=connection)
    attach_consumers(connection, settings.processor_concurrency, callback)
    logger.info(
        "processor consuming",
        extra={"prefetch": 1, "concurrency": settings.processor_concurrency},
    )
    run_sweep()
    last_sweep = time.monotonic()
    while not stopping:
        connection.process_data_events(time_limit=1)
        if time.monotonic() - last_sweep >= settings.sweep_interval_seconds:
            run_sweep()
            last_sweep = time.monotonic()
    logger.info("processor stopping")
    try:
        connection.close()
    finally:
        ocr.close()
        embedding.close()
