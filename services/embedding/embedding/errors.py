class ConfigError(Exception):
    """Configuration is missing or invalid. The message names the variable only."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Invalid configuration: {name}")


class ValidationFailed(Exception):
    def __init__(self, message: str, fields: list[str]) -> None:
        self.message = message
        self.fields = fields
        super().__init__(message)


class UpstreamFailed(Exception):
    pass


class UpstreamTimeout(Exception):
    pass


class ModelLoadError(Exception):
    """Weights or llama-server did not become ready. The process must exit."""
