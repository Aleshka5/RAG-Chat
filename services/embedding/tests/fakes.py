from collections.abc import Callable

DIMENSION = 768


def unit_vector(index: int) -> list[float]:
    vector = [0.0] * DIMENSION
    vector[index % DIMENSION] = 1.0
    return vector


class FakeEncoder:
    def __init__(
        self,
        vectors: list[list[float]] | None = None,
        error: Exception | None = None,
        *,
        healthy: bool = True,
    ) -> None:
        self.vectors = vectors
        self.error = error
        self._healthy = healthy
        self.seen: list[list[str]] = []
        self.image_batches: list[list[bytes]] = []
        self.request_ids: list[str | None] = []
        self.closed = False

    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]:
        self.seen.append(list(texts))
        self.request_ids.append(request_id)
        return self._vectors(len(texts))

    def embed_images(
        self, images: list[bytes], *, request_id: str | None = None
    ) -> list[list[float]]:
        self.image_batches.append(list(images))
        self.request_ids.append(request_id)
        return self._vectors(len(images))

    def _vectors(self, count: int) -> list[list[float]]:
        if self.error is not None:
            raise self.error
        if self.vectors is not None:
            return self.vectors
        return [unit_vector(index) for index in range(count)]

    def healthy(self) -> bool:
        return self._healthy

    def close(self) -> None:
        self.closed = True


class FakeCounter:
    def __init__(self, count: int | Callable[[str], int]) -> None:
        self._count = count
        self.seen: list[str] = []

    def count(self, text: str) -> int:
        self.seen.append(text)
        if callable(self._count):
            return self._count(text)
        return self._count
