"""Process entrypoint. The model is loaded before the port is opened."""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import uvicorn

from ocr_service.app import create_app
from ocr_service.config import ConfigError, Settings
from ocr_service.engine import CPU_MATH_THREADS, PaddleMultilingualEngine, pin_native_thread_pools

logger = logging.getLogger("ocr")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logging.basicConfig(level=logging.ERROR, stream=sys.stdout)
        logger.error("invalid configuration variable: %s", exc.name)
        raise SystemExit(1) from None

    configure_logging(settings.log_level)
    # Repeat the pin for `python -m ocr_service.main`. The package entry
    # already sets the variables before this module is imported.
    pin_native_thread_pools()
    logger.info(
        "starting OCR model=%s port=%s timeout_seconds=%s cpu_threads=%s",
        settings.ocr_model,
        settings.ocr_port,
        settings.ocr_timeout,
        CPU_MATH_THREADS,
    )
    # Build and run the predictor on one worker. set_cpu_math_library_num_threads
    # applies to the calling thread only, and the predictor is not shared.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
    try:
        engine = executor.submit(PaddleMultilingualEngine).result()
    except (Exception, SystemExit):
        executor.shutdown(wait=False, cancel_futures=True)
        logger.exception("OCR model failed to load")
        raise SystemExit(1) from None

    app = create_app(engine, settings, executor)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.ocr_port,
        log_level=settings.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
