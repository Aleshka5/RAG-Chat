import time
from collections import OrderedDict
from collections.abc import Callable


class QueryVectorCache:
    """Process-local LRU of image-search query vectors.

    The key is ``(user_id, trimmed query)``. Only the vector is stored.
    A read refreshes recency and does not extend the TTL.
    """

    def __init__(
        self,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._items: OrderedDict[tuple[str, str], tuple[float, list[float]]] = OrderedDict()

    def get(self, user_id: str, query: str) -> list[float] | None:
        key = (user_id, query)
        found = self._items.get(key)
        if found is None:
            return None
        stored_at, vector = found
        if self._clock() - stored_at >= self._ttl_seconds:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return list(vector)

    def put(self, user_id: str, query: str, vector: list[float]) -> None:
        key = (user_id, query)
        self._items[key] = (self._clock(), list(vector))
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)
