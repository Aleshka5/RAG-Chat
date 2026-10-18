from deletion_worker.topology import (
    DELETION_DEAD,
    DELETION_QUEUE,
    PROCESSING_DEAD,
    PROCESSING_QUEUE,
    declare_topology,
    register_consumer,
)
from tests.fakes import RecordingChannel


def test_declare_topology_is_idempotent_and_wires_dead_letters() -> None:
    channel = RecordingChannel()
    declare_topology(channel, "doc_events", "doc_events_dlq")
    first = list(channel.calls)
    declare_topology(channel, "doc_events", "doc_events_dlq")
    assert channel.calls == first + first

    queues = {call[1]["queue"]: call[1] for call in channel.calls if call[0] == "queue_declare"}
    assert queues[DELETION_QUEUE]["durable"] is True
    assert queues[DELETION_QUEUE]["arguments"] == {
        "x-dead-letter-exchange": "doc_events_dlq",
        "x-dead-letter-routing-key": DELETION_DEAD,
    }
    assert queues[PROCESSING_QUEUE]["arguments"]["x-dead-letter-routing-key"] == PROCESSING_DEAD
    assert queues[DELETION_DEAD]["durable"] is True
    assert "arguments" not in queues[DELETION_DEAD]

    binds = [call[1] for call in channel.calls if call[0] == "queue_bind"]
    assert {
        "queue": DELETION_QUEUE,
        "exchange": "doc_events",
        "routing_key": "doc.delete",
    } in binds
    assert {
        "queue": DELETION_DEAD,
        "exchange": "doc_events_dlq",
        "routing_key": DELETION_DEAD,
    } in binds


def test_consumer_sets_prefetch_one_before_consume() -> None:
    channel = RecordingChannel()
    register_consumer(channel, lambda *_args: None)
    assert channel.calls == [
        ("basic_qos", 1),
        ("basic_consume", DELETION_QUEUE, False),
    ]
