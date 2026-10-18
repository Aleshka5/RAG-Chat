"""``X-Request-Id`` from docs/architecture.md and docs/api.md.

An incoming UUID is kept and returned on the response. Anything else becomes
a new UUID. Outgoing HTTP uses ``X-Request-Id``. AMQP uses ``x-request-id``
only when the id is known.
"""

from collections.abc import Mapping
from uuid import UUID, uuid4

from rag_common.auth import canonical_uuid

REQUEST_ID_HEADER = "X-Request-Id"
AMQP_REQUEST_ID_HEADER = "x-request-id"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            text = value.strip()
            return text or None
    return None


def resolve_request_id(headers: Mapping[str, str] | None) -> str:
    """Return the accepted request id, or a new UUID when the header is absent or not a UUID."""
    if headers is not None:
        raw = _header(headers, REQUEST_ID_HEADER)
        if raw is not None:
            canonical = canonical_uuid(raw)
            if canonical is not None:
                return canonical
    return str(uuid4())


def response_headers(request_id: str) -> dict[str, str]:
    return {REQUEST_ID_HEADER: str(UUID(request_id))}


def outgoing_http_headers(
    request_id: str,
    headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    merged = dict(headers or {})
    merged[REQUEST_ID_HEADER] = str(UUID(request_id))
    return merged


def amqp_headers(request_id: str | None) -> dict[str, str]:
    if not request_id:
        return {}
    return {AMQP_REQUEST_ID_HEADER: str(UUID(request_id))}
