import math

from embedding.constants import UNIT_NORM_TOLERANCE
from embedding.errors import UpstreamFailed


def project_embeddings(raw: object, count: int, dimension: int) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) != count:
        raise UpstreamFailed("Embedding count does not match texts")
    return [ensure_unit_vector(item, dimension) for item in raw]


def ensure_unit_vector(values: object, dimension: int) -> list[float]:
    """Keep a finite vector of ``dimension`` and L2-normalize it when it is not unit length."""
    if not isinstance(values, list) or len(values) != dimension:
        raise UpstreamFailed("Embedding vector has the wrong dimension")
    cleaned: list[float] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise UpstreamFailed("Embedding vector is not numeric")
        number = float(item)
        if not math.isfinite(number):
            raise UpstreamFailed("Embedding vector is not finite")
        cleaned.append(number)
    norm = math.sqrt(sum(number * number for number in cleaned))
    if not math.isfinite(norm) or norm == 0.0:
        raise UpstreamFailed("Embedding vector has zero norm")
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        cleaned = [number / norm for number in cleaned]
    return cleaned
