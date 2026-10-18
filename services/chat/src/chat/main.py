from chat.app import create_app
from chat.config import load_settings
from chat.logging_config import configure_logging

configure_logging("info")
settings = load_settings()
configure_logging(settings.log_level)
app = create_app(settings)
