from datetime import timedelta

from deletion_worker.delivery import handle_delivery
from deletion_worker.model import Outcome
from tests.conftest import FILE_ID, NOW, S3_KEY, USER_ID, World, delete_body, stale_time
from tests.fakes import RecordingChannel


def test_ready_file_is_conditionally_moved_to_deleting_then_removed(world: World) -> None:
    world.add_file(status="ready", error=None)
    outcome = world.handler.handle(delete_body())
    assert outcome is Outcome.ACK
    assert world.events[0] == ("mark_deleting", FILE_ID)
    assert world.files.docs[FILE_ID].status == "deleted"
    assert S3_KEY not in world.objects.objects


def test_fresh_processing_is_dead_lettered_without_storage_changes(world: World) -> None:
    world.add_file(status="processing", updated_at=NOW)
    before = dict(world.objects.objects)

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.NACK
    assert world.events == []
    assert world.objects.objects == before
    assert world.files.docs[FILE_ID].status == "processing"


def test_processing_at_stale_boundary_is_still_fresh(world: World) -> None:
    world.add_file(status="processing", updated_at=NOW - timedelta(seconds=900))
    assert world.handler.handle(delete_body()) is Outcome.NACK
    assert world.events == []
    assert world.files.docs[FILE_ID].status == "processing"


def test_stale_processing_is_deleted(world: World) -> None:
    world.add_file(status="processing", updated_at=stale_time())
    assert world.handler.handle(delete_body()) is Outcome.ACK
    assert world.files.docs[FILE_ID].status == "deleted"
    assert ("delete_points", USER_ID, FILE_ID) in world.events


def test_conditional_update_lost_to_deleted_acks_without_storage_writes(world: World) -> None:
    world.add_file(status="ready")

    def lose_to_deleted(file_id: str, now: object, stale_before: object) -> bool:
        world.events.append(("mark_deleting", file_id))
        world.files.docs[file_id].status = "deleted"
        return False

    world.files.mark_deleting = lose_to_deleted  # type: ignore[method-assign]

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.ACK
    assert world.events == [("mark_deleting", FILE_ID)]
    assert S3_KEY in world.objects.objects
    assert (USER_ID, FILE_ID) in world.vectors.points
    assert FILE_ID in world.files.pages


def test_conditional_update_lost_to_fresh_processing_nacks(world: World) -> None:
    world.add_file(status="ready")

    def lose_to_processing(file_id: str, now: object, stale_before: object) -> bool:
        world.events.append(("mark_deleting", file_id))
        document = world.files.docs[file_id]
        document.status = "processing"
        document.updated_at = NOW
        return False

    world.files.mark_deleting = lose_to_processing  # type: ignore[method-assign]

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.NACK
    assert ("delete_object", S3_KEY) not in world.events
    assert world.files.docs[FILE_ID].status == "processing"


def test_s3_key_mismatch_nacks_without_deleting_either_key(world: World) -> None:
    world.add_file(status="deleting")
    foreign = "files/other-user/other-file/foreign.pdf"
    world.objects.objects[foreign] = b"%PDF"

    outcome = world.handler.handle(delete_body(s3_key=foreign))

    assert outcome is Outcome.NACK
    assert world.events == []
    assert S3_KEY in world.objects.objects
    assert foreign in world.objects.objects
    assert world.files.docs[FILE_ID].status == "deleting"


def test_user_mismatch_nacks_without_changes(world: World) -> None:
    world.add_file(status="deleting")
    other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    outcome = world.handler.handle(delete_body(user_id=other))
    assert outcome is Outcome.NACK
    assert world.events == []
    assert world.files.docs[FILE_ID].status == "deleting"


def test_missing_document_purges_message_targets_and_acks(world: World) -> None:
    world.objects.objects[S3_KEY] = b"%PDF"
    world.vectors.points[(USER_ID, FILE_ID)] = ["orphan"]
    world.files.pages[FILE_ID] = [{"page_number": 1}]

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.ACK
    assert world.events == [
        ("delete_object", S3_KEY),
        ("delete_points", USER_ID, FILE_ID),
        ("delete_pages", FILE_ID),
    ]
    assert S3_KEY not in world.objects.objects
    assert (USER_ID, FILE_ID) not in world.vectors.points
    assert FILE_ID not in world.files.pages


def test_missing_object_is_success(world: World) -> None:
    world.add_file(status="deleting")
    world.objects.objects.clear()
    assert world.handler.handle(delete_body()) is Outcome.ACK
    assert world.files.docs[FILE_ID].status == "deleted"


def test_invalid_messages_nack_without_reads(world: World) -> None:
    world.add_file(status="deleting")
    bodies = [
        b"{",
        delete_body(schema_version=2),
        delete_body(schema_version=True),
        delete_body(message_type="doc.process"),
        delete_body(file_id="not-a-uuid"),
        delete_body(s3_key=""),
        delete_body(user_id="91A0B1C2-3D4E-4F50-8617-18293A4B5C6D"),
    ]
    for body in bodies:
        world.events.clear()
        assert world.handler.handle(body) is Outcome.NACK
        assert world.events == []
        assert world.files.docs[FILE_ID].status == "deleting"


def test_minio_failure_after_three_attempts_nacks_and_keeps_deleting(world: World) -> None:
    world.add_file(status="deleting")
    world.objects.failures = 3

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.NACK
    assert world.events.count(("delete_object", S3_KEY)) == 3
    assert ("delete_points", USER_ID, FILE_ID) not in world.events
    assert world.files.docs[FILE_ID].status == "deleting"
    assert world.files.docs[FILE_ID].delete_claimed_at is not None
    assert S3_KEY in world.objects.objects
    assert world.sleeps == [0.5, 1.0]


def test_qdrant_failure_after_three_attempts_nacks(world: World) -> None:
    world.add_file(status="deleting")
    world.vectors.failures = 3
    outcome = world.handler.handle(delete_body())
    assert outcome is Outcome.NACK
    assert world.events.count(("delete_points", USER_ID, FILE_ID)) == 3
    assert world.files.docs[FILE_ID].status == "deleting"
    assert S3_KEY not in world.objects.objects


def test_claim_failure_bumps_updated_at_and_nacks(world: World) -> None:
    original = NOW - timedelta(seconds=30)
    world.add_file(status="deleting", updated_at=original)
    world.files.claim_failures = 3

    outcome = world.handler.handle(delete_body())

    document = world.files.docs[FILE_ID]
    assert outcome is Outcome.NACK
    assert document.delete_claimed_at is None
    assert document.status == "deleting"
    assert document.updated_at == NOW
    assert document.updated_at != original
    assert ("touch_updated_at", FILE_ID) in world.events
    assert ("delete_object", S3_KEY) not in world.events
    assert S3_KEY in world.objects.objects


def test_final_status_write_retries_once_then_succeeds(world: World) -> None:
    world.add_file(status="deleting")
    world.files.delete_failures = 1
    assert world.handler.handle(delete_body()) is Outcome.ACK
    assert world.files.docs[FILE_ID].status == "deleted"
    assert world.sleeps == [0.5]


def test_final_status_write_nacks_after_extra_attempt(world: World) -> None:
    world.add_file(status="deleting")
    world.files.delete_failures = 2

    outcome = world.handler.handle(delete_body())

    assert outcome is Outcome.NACK
    assert world.files.docs[FILE_ID].status == "deleting"
    assert S3_KEY not in world.objects.objects
    assert (USER_ID, FILE_ID) not in world.vectors.points
    assert FILE_ID not in world.files.pages
    assert world.events.count(("mark_deleted", FILE_ID)) == 0


def test_delivery_acks_and_dead_letters_without_requeue(world: World) -> None:
    world.add_file(status="deleted")
    channel = RecordingChannel()
    crashes: list[str] = []

    class Method:
        delivery_tag = 11

    class Properties:
        headers = {"x-request-id": "req-9"}

    handle_delivery(
        channel,
        Method(),
        Properties(),
        delete_body(),
        world.handler,
        lambda: crashes.append("crash"),
    )
    assert channel.acks == [11]
    assert channel.nacks == []

    handle_delivery(
        channel,
        Method(),
        Properties(),
        b"not-json",
        world.handler,
        lambda: crashes.append("crash"),
    )
    assert channel.nacks == [(11, False)]
    assert crashes == []


def test_delivery_crash_leaves_message_unacked(world: World) -> None:
    world.add_file(status="deleting")
    world.objects.crash_after_delete = True
    channel = RecordingChannel()
    crashes: list[str] = []

    class Method:
        delivery_tag = 4

    class Properties:
        headers = None

    handle_delivery(
        channel,
        Method(),
        Properties(),
        delete_body(),
        world.handler,
        lambda: crashes.append("crash"),
    )
    assert channel.acks == []
    assert channel.nacks == []
    assert crashes == ["crash"]
