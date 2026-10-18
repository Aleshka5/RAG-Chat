"""Process entrypoint."""

import logging

import uvicorn

from file_collector.app import create_app
from file_collector.config import Settings
from file_collector.errors import ConfigError
from file_collector.logging import configure_logging

logger = logging.getLogger("file_collector")


def main() -> None:
    configure_logging("info")
    try:
        settings = Settings.from_env()
    except ConfigError:
        raise SystemExit(1) from None
    configure_logging(settings.log_level)
    app = create_app(settings)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_config=None,
        access_log=False,
    )
