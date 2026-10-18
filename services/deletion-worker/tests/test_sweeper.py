import json
from datetime import timedelta

from deletion_worker.messages import parse_delete_message
from deletion_worker.model import FileRecord
from deletion_worker.publisher import RabbitDeletePublisher
from deletion_worker.sweeper import Sweeper
from tests.conftest import FILE_ID, NOW, USER_ID, World
from tests.fakes import MemoryPublisher, RecordingChannel


def test_sweeper_publishes_only_old_unclaimed_deletes(world: World) -> None:
    world.add_file(status="deleting", updated_at=NOW - timedelta(seconds=121))
    claimed_id = "11111111-2222-4333-8444-555555555555"
    fresh = world.files.docs[FILE_ID]
    claimed = type(fresh)(
        file_id=claimed_id,
        user_id=USER_ID,
        s3_key="files/claimed",
        status="deleting",
        updated_at=NOW - timedelta(seconds=500),
        delete_claimed_at=NOW,
    )
    fresh_delete = type(fresh)(
        file_id="22222222-3333-4444-8555-666666666666",
        user_id=USER_ID,
        s3_key="files/fresh",
        status="deleting",
        updated_at=NOW - timedelta(seconds=120),
        delete_claimed_at=None,
    )
    ready = type(fresh)(
        file_id="33333333-4444-4555-8666-777777777777",
        user_id=USER_ID,
        s3_key="files/ready",
        status="ready",
        updated_at=NOW - timedelta(seconds=500),
        delete_claimed_at=None,
    )
    world.files.docs[claimed.file_id] = claimed
    world.files.docs[fresh_delete.file_id] = fresh_delete
    world.files.docs[ready.file_id] = ready
    publisher = MemoryPublisher()
    sweeper = Sweeper(
        world.files,
        publisher,
        delete_requeue_after_seconds=120,
        clock=lambda: NOW,
    )

    assert sweeper.run_once() == 1
    assert [item.file_id for item in publisher.published] == [FILE_ID]


def test_sweeper_continues_after_publish_failure(world: World) -> None:
    world.add_file(status="deleting", updated_at=NOW - timedelta(seconds=121))
    other = world.files.docs[FILE_ID]
    second_id = "44444444-5555-4666-8777-888888888888"
    world.files.docs[second_id] = type(other)(
        file_id=second_id,
        user_id=USER_ID,
        s3_key="files/second",
        status="deleting",
        updated_at=NOW - timedelta(seconds=121),
        delete_claimed_at=None,
    )
    publisher = MemoryPublisher()
    publisher.fail_ids.add(FILE_ID)
    sweeper = Sweeper(
        world.files,
        publisher,
        delete_requeue_after_seconds=120,
        clock=lambda: NOW,
    )
    assert sweeper.run_once() == 1
    assert [item.file_id for item in publisher.published] == [second_id]


def test_publisher_confirms_doc_delete_body() -> None:
    channel = RecordingChannel()
    publisher = RabbitDeletePublisher(channel, "doc_events")
    file = FileRecord(
        file_id=FILE_ID,
        user_id=USER_ID,
        s3_key="files/a",
        status="deleting",
        updated_at=NOW,
        delete_claimed_at=None,
    )
    first = publisher.publish_delete(file, now=NOW)
    second = publisher.publish_delete(file, now=NOW)
    assert first != second
    assert channel.calls[0] == ("confirm_delivery",)
    sent = channel.published[0]
    assert sent["exchange"] == "doc_events"
    assert sent["routing_key"] == "doc.delete"
    assert sent["mandatory"] is True
    properties = sent["properties"]
    raw_body = sent["body"]
    assert isinstance(raw_body, bytes)
    body = json.loads(raw_body)
    parsed = parse_delete_message(raw_body)
    assert parsed.file_id == FILE_ID
    assert parsed.message_id == first
    assert properties.content_type == "application/json"
    assert properties.content_encoding == "utf-8"
    assert properties.delivery_mode == 2
    assert properties.app_id == "deletion-worker"
    assert properties.message_id == first
    assert properties.headers["x-request-id"]
    assert "x-death" not in body
    assert "x-death" not in properties.headers
