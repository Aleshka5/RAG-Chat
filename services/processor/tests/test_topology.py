from pathlib import Path

from processor.consumer import PREFETCH_COUNT, attach_consumer, attach_consumers
from processor.topology import (
    QUEUE_DELETION,
    QUEUE_DELETION_DEAD,
    QUEUE_PROCESSING,
    QUEUE_PROCESSING_DEAD,
    ROUTING_DELETE,
    ROUTING_PROCESS,
    declare_topology,
    processing_queue_arguments,
)


class FakeChannel:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def exchange_declare(self, **kwargs):
        self.calls.append(("exchange", kwargs))

    def queue_declare(self, **kwargs):
        self.calls.append(("queue", kwargs))

    def queue_bind(self, **kwargs):
        self.calls.append(("bind", kwargs))

    def basic_qos(self, **kwargs):
        self.calls.append(("qos", kwargs))

    def basic_consume(self, **kwargs):
        self.calls.append(("consume", kwargs))


class FakeConnection:
    def __init__(self) -> None:
        self.channels: list[FakeChannel] = []

    def channel(self) -> FakeChannel:
        channel = FakeChannel()
        self.channels.append(channel)
        return channel


def test_topology_matches_messaging_spec() -> None:
    channel = FakeChannel()
    declare_topology(channel, "doc_events", "doc_events_dlq")
    declare_topology(channel, "doc_events", "doc_events_dlq")
    exchanges = [call for call in channel.calls if call[0] == "exchange"]
    assert exchanges[0][1] == {
        "exchange": "doc_events",
        "exchange_type": "direct",
        "durable": True,
    }
    assert exchanges[1][1]["exchange"] == "doc_events_dlq"
    queues = {call[1]["queue"]: call[1] for call in channel.calls if call[0] == "queue"}
    assert set(queues) == {
        QUEUE_PROCESSING,
        QUEUE_DELETION,
        QUEUE_PROCESSING_DEAD,
        QUEUE_DELETION_DEAD,
    }
    assert queues[QUEUE_PROCESSING]["arguments"] == processing_queue_arguments("doc_events_dlq")
    assert "x-max-priority" not in queues[QUEUE_PROCESSING]["arguments"]
    assert queues[QUEUE_PROCESSING]["durable"] is True
    binds = [call[1] for call in channel.calls if call[0] == "bind"]
    assert {(item["queue"], item["exchange"], item["routing_key"]) for item in binds} == {
        (QUEUE_PROCESSING, "doc_events", ROUTING_PROCESS),
        (QUEUE_DELETION, "doc_events", ROUTING_DELETE),
        (QUEUE_PROCESSING_DEAD, "doc_events_dlq", QUEUE_PROCESSING_DEAD),
        (QUEUE_DELETION_DEAD, "doc_events_dlq", QUEUE_DELETION_DEAD),
    }


def test_prefetch_is_one_and_documented() -> None:
    assert PREFETCH_COUNT == 1
    channel = FakeChannel()
    attach_consumer(channel, lambda *_args: None)
    assert [call[0] for call in channel.calls] == ["qos", "consume"]
    assert channel.calls[0][1]["prefetch_count"] == 1
    assert channel.calls[1][1]["queue"] == QUEUE_PROCESSING
    assert channel.calls[1][1]["auto_ack"] is False
    connection = FakeConnection()
    attach_consumers(connection, 2, lambda *_args: None)
    assert len(connection.channels) == 2
    assert all(ch.calls[0][1]["prefetch_count"] == 1 for ch in connection.channels)
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
    assert "prefetch=1" in readme
