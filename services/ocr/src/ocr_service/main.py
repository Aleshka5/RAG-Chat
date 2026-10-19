"""Process entrypoint. The model is loaded before the port is opened."""

from __future__ import annotations

import logging
import sys

import uvicorn

from ocr_service.app import create_app
from ocr_service.config import ConfigError, Settings
from ocr_service.engine import SuryaEngine
from ocr_service.llama import start_reader

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
    logger.info(
        "starting OCR model=%s port=%s timeout_seconds=%s",
        settings.ocr_model,
        settings.ocr_port,
        settings.ocr_timeout,
    )
    try:
        engine = SuryaEngine(start_reader(settings))
    except Exception:
        logger.exception("OCR model failed to load")
        raise SystemExit(1) from None

    app = create_app(engine, settings)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.ocr_port,
        log_level=settings.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
