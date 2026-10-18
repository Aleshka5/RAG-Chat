import json

import pytest

from rag_common.messages import DocProcess
from rag_common.rabbitmq import PREFETCH_COUNT, apply_prefetch, build_publish, declare_topology

PROCESS = {
    "schema_version": 1,
    "message_type": "doc.process",
    "message_id": "f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5",
    "file_id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
    "user_id": "91a0b1c2-3d4e-4f50-8617-18293a4b5c6d",
    "s3_key": (
        "files/91a0b1c2-3d4e-4f50-8617-18293a4b5c6d/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/Otchet.pdf"
    ),
    "file_name": "Отчёт.pdf",
    "content_type": "application/pdf",
    "created_at": "2026-10-18T20:00:00Z",
}


class FakeChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def exchange_declare(self, *, exchange: str, exchange_type: str, durable: bool) -> None:
        self.calls.append(
            ("exchange", {"exchange": exchange, "exchange_type": exchange_type, "durable": durable})
        )

    def queue_declare(self, *, queue: str, durable: bool, arguments: dict | None = None) -> None:
        self.calls.append(("queue", {"queue": queue, "durable": durable, "arguments": arguments}))

    def queue_bind(self, *, queue: str, exchange: str, routing_key: str) -> None:
        self.calls.append(
            ("bind", {"queue": queue, "exchange": exchange, "routing_key": routing_key})
        )

    def basic_qos(self, *, prefetch_count: int) -> None:
        self.calls.append(("qos", {"prefetch_count": prefetch_count}))


def test_declare_is_idempotent_and_matches_messaging() -> None:
    channel = FakeChannel()
    declare_topology(channel)
    declare_topology(channel)
    first = channel.calls[: len(channel.calls) // 2]
    second = channel.calls[len(channel.calls) // 2 :]
    assert first == second

    exchanges = [call for call in first if call[0] == "exchange"]
    assert exchanges == [
        ("exchange", {"exchange": "doc_events", "exchange_type": "direct", "durable": True}),
        ("exchange", {"exchange": "doc_events_dlq", "exchange_type": "direct", "durable": True}),
    ]

    queues = {call[1]["queue"]: call[1] for call in first if call[0] == "queue"}
    assert queues["doc.processing"]["arguments"] == {
        "x-dead-letter-exchange": "doc_events_dlq",
        "x-dead-letter-routing-key": "doc.processing.dead",
    }
    assert queues["doc.deletion"]["arguments"] == {
        "x-dead-letter-exchange": "doc_events_dlq",
        "x-dead-letter-routing-key": "doc.deletion.dead",
    }
    assert queues["doc.processing.dead"]["arguments"] is None
    assert queues["doc.deletion.dead"]["arguments"] is None
    for item in queues.values():
        assert item["durable"] is True
        assert "x-max-priority" not in (item["arguments"] or {})

    binds = [call[1] for call in first if call[0] == "bind"]
    assert binds == [
        {"queue": "doc.processing", "exchange": "doc_events", "routing_key": "doc.process"},
        {"queue": "doc.deletion", "exchange": "doc_events", "routing_key": "doc.delete"},
        {
            "queue": "doc.processing.dead",
            "exchange": "doc_events_dlq",
            "routing_key": "doc.processing.dead",
        },
        {
            "queue": "doc.deletion.dead",
            "exchange": "doc_events_dlq",
            "routing_key": "doc.deletion.dead",
        },
    ]


def test_prefetch_is_one() -> None:
    channel = FakeChannel()
    apply_prefetch(channel)
    assert channel.calls == [("qos", {"prefetch_count": PREFETCH_COUNT})]
    assert PREFETCH_COUNT == 1


def test_publish_properties() -> None:
    message = DocProcess.model_validate(PROCESS)
    spec = build_publish(
        message,
        app_id="file-collector",
        timestamp=1_760_000_000,
        request_id="f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5",
    )
    assert spec.content_type == "application/json"
    assert spec.content_encoding == "utf-8"
    assert spec.delivery_mode == 2
    assert spec.message_id == PROCESS["message_id"]
    assert spec.routing_key == "doc.process"
    assert spec.app_id == "file-collector"
    assert spec.timestamp == 1_760_000_000
    assert spec.headers == {"x-request-id": "f0c1d2e3-4a5b-4c6d-8e7f-8091a2b3c4d5"}
    body = json.loads(spec.body.decode("utf-8"))
    assert body == PROCESS
    assert "x-death" not in body

    without_request = build_publish(message, app_id="processor", timestamp=1)
    assert without_request.headers == {}


def test_publish_rejects_unknown_app_id() -> None:
    message = DocProcess.model_validate(PROCESS)
    with pytest.raises(ValueError):
        build_publish(message, app_id="file_collector", timestamp=1)
