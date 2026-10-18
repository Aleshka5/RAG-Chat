class PermanentMessageError(Exception):
    """The delivery cannot succeed. The broker message goes to the dead queue."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TransientStorageError(Exception):
    """A dependency call failed and may succeed on another attempt."""


class StorageOperationError(Exception):
    """Retries for one deletion step are exhausted."""

    def __init__(self, step: str) -> None:
        self.step = step
        super().__init__(step)


class PublishError(Exception):
    """Broker did not confirm a doc.delete publication."""
