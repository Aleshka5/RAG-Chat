import logging

import uvicorn

from embedding.app import create_app
from embedding.config import Settings, configure_logging
from embedding.errors import ConfigError


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger("embedding").error("%s", exc)
        raise SystemExit(1) from exc
    configure_logging(settings.log_level)
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
