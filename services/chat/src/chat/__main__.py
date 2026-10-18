import uvicorn

from chat.config import load_settings
from chat.main import app


def main() -> None:
    loaded = load_settings()
    uvicorn.run(app, host="0.0.0.0", port=loaded.chat_port, log_config=None)


if __name__ == "__main__":
    main()
