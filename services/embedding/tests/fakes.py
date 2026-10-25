from collections.abc import Callable

from embedding.encoder import ImageInput


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
        self.image_seen: list[list[ImageInput]] = []
        self.request_ids: list[str | None] = []
        self.closed = False

    def embed(self, texts: list[str], *, request_id: str | None = None) -> list[list[float]]:
        self.seen.append(list(texts))
        self.request_ids.append(request_id)
        if self.error is not None:
            raise self.error
        if self.vectors is not None:
            return self.vectors
        vectors: list[list[float]] = []
        for index, _text in enumerate(texts):
            vector = [0.0] * 768
            vector[index % 768] = 1.0
            vectors.append(vector)
        return vectors

    def embed_images(
        self,
        images: list[ImageInput],
        *,
        request_id: str | None = None,
    ) -> list[list[float]]:
        self.image_seen.append(list(images))
        self.request_ids.append(request_id)
        if self.error is not None:
            raise self.error
        if self.vectors is not None:
            return self.vectors
        vectors: list[list[float]] = []
        for index, _image in enumerate(images):
            vector = [0.0] * 768
            vector[index % 768] = 1.0
            vectors.append(vector)
        return vectors

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
