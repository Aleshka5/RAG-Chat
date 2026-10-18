from uuid import UUID

from rag_common.request_id import (
    AMQP_REQUEST_ID_HEADER,
    REQUEST_ID_HEADER,
    amqp_headers,
    outgoing_http_headers,
    resolve_request_id,
    response_headers,
)

REQUEST = "f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5"


def test_missing_header_is_a_new_uuid() -> None:
    first = resolve_request_id(None)
    second = resolve_request_id({})
    UUID(first)
    UUID(second)
    assert first != second


def test_invalid_header_is_replaced() -> None:
    value = resolve_request_id({REQUEST_ID_HEADER: "not-a-uuid"})
    UUID(value)
    assert value != "not-a-uuid"


def test_accepted_uuid_is_canonical_and_propagated() -> None:
    resolved = resolve_request_id({"x-request-id": REQUEST.upper()})
    assert resolved == REQUEST
    assert response_headers(resolved) == {REQUEST_ID_HEADER: REQUEST}
    outgoing = outgoing_http_headers(resolved, {"Accept": "application/json"})
    assert outgoing[REQUEST_ID_HEADER] == REQUEST
    assert outgoing["Accept"] == "application/json"
    assert amqp_headers(resolved) == {AMQP_REQUEST_ID_HEADER: REQUEST}
    assert amqp_headers(None) == {}
    assert amqp_headers("") == {}
