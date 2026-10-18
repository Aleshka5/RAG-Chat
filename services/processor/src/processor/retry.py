from collections.abc import Callable

BACKOFF_SECONDS = (0.5, 1.0, 2.0)


def retry_call[T](
    operation: Callable[[], T],
    *,
    attempts: int,
    sleeper: Callable[[float], None],
    is_retryable: Callable[[Exception], bool],
) -> T:
    """Run ``operation`` up to ``attempts`` times.

    Pauses before each retry are 0.5s, 1s, then 2s. HTTP 4xx is not retried
    when ``is_retryable`` returns false. The last failure is raised as-is.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            return operation()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            if not is_retryable(exc):
                raise
            last_error = exc
            if index + 1 >= attempts:
                break
            sleeper(BACKOFF_SECONDS[min(index, len(BACKOFF_SECONDS) - 1)])
    assert last_error is not None
    raise last_error
