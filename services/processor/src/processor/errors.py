class TransientFailure(Exception):
    """A step failed in a way that a later delivery can continue from the checkpoint."""

    def __init__(self, reason: str, *, permanent_code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.permanent_code = permanent_code


class PermanentFailure(Exception):
    """The file cannot become ready. ``code`` is written to ``files.error``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class InvalidMessage(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ConfigError(Exception):
    pass
