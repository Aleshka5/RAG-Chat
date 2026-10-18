import logging
import os

from deletion_worker.config import load_settings
from deletion_worker.log import configure_logging
from deletion_worker.service import build_service

logger = logging.getLogger("deletion_worker")


def main() -> None:
    configure_logging(os.environ.get("LOG_LEVEL", "info"))
    settings = load_settings()
    configure_logging(settings.log_level)
    logger.info("deletion worker starting")
    service = build_service(settings)
    service.run()
