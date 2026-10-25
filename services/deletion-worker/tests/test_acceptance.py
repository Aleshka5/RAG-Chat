import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from deletion_worker.handler import DeletionHandler
from deletion_worker.model import Outcome
from deletion_worker.vector_store import QdrantVectorStore
from tests.conftest import FILE_ID, NOW, S3_KEY, USER_ID, World, delete_body, snapshot


def test_full_delete_removes_object_points_pages_and_sets_deleted(world: World) -> None:
    world.add_file(status="deleting")
    other_file = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
    other_user = "88888888-9999-4aaa-8bbb-cccccccccccc"
    world.files.pages[other_file] = [{"page_number": 1, "text": "keep"}]
    world.vectors.points[(USER_ID, other_file)] = ["other-file"]
    world.vectors.points[(other_user, FILE_ID)] = ["other-user"]
    world.objects.objects["files/keep"] = b"%PDF"
    body = delete_body()

    outcome = world.handler.handle(body, request_id="req-1")

    assert outcome is Outcome.ACK
    assert S3_KEY not in world.objects.objects
    assert "files/keep" in world.objects.objects
    assert (USER_ID, FILE_ID) not in world.vectors.points
    assert world.vectors.points[(USER_ID, other_file)] == ["other-file"]
    assert world.vectors.points[(other_user, FILE_ID)] == ["other-user"]
    assert FILE_ID not in world.files.pages
    assert other_file in world.files.pages
    document = world.files.docs[FILE_ID]
    assert document.status == "deleted"
    assert document.delete_claimed_at is not None
    assert world.events == [
        ("claim", FILE_ID),
        ("delete_object", S3_KEY),
        ("delete_points", USER_ID, FILE_ID),
        ("delete_pages", FILE_ID),
        ("mark_deleted", FILE_ID),
    ]


def test_duplicate_message_acks_without_changes(world: World) -> None:
    world.add_file(status="deleting")
    body = delete_body()
    assert world.handler.handle(body) is Outcome.ACK
    after_first = snapshot(world.files, world.objects, world.vectors)
    events_after_first = list(world.events)

    outcome = world.handler.handle(body)

    assert outcome is Outcome.ACK
    assert snapshot(world.files, world.objects, world.vectors) == after_first
    assert world.events == events_after_first
    assert world.files.docs[FILE_ID].status == "deleted"


def test_crash_after_object_delete_is_repaired_by_redelivery(world: World) -> None:
    world.add_file(status="deleting")
    world.objects.crash_after_delete = True
    body = delete_body()

    with pytest.raises(RuntimeError, match="crash after object delete"):
        world.handler.handle(body)

    assert S3_KEY not in world.objects.objects
    assert (USER_ID, FILE_ID) in world.vectors.points
    assert FILE_ID in world.files.pages
    assert world.files.docs[FILE_ID].status == "deleting"
    assert world.files.docs[FILE_ID].delete_claimed_at is not None

    outcome = world.handler.handle(body)

    assert outcome is Outcome.ACK
    assert S3_KEY not in world.objects.objects
    assert (USER_ID, FILE_ID) not in world.vectors.points
    assert FILE_ID not in world.files.pages
    assert world.files.docs[FILE_ID].status == "deleted"
    assert world.events.count(("delete_object", S3_KEY)) == 2


def test_delete_clears_document_and_image_collections() -> None:
    def run(*, missing_images: bool) -> None:
        world = World()
        world.add_file(status="deleting")

        class Client:
            def delete(self, collection_name: str, points_selector: object, wait: bool) -> None:
                world.events.append(("qdrant_delete", collection_name))
                must = points_selector.filter.must  # type: ignore[attr-defined]
                assert [(item.key, item.match.value) for item in must] == [
                    ("user_id", USER_ID),
                    ("document_id", FILE_ID),
                ]
                assert wait is True
                if missing_images and collection_name == "images":
                    raise UnexpectedResponse(404, "not found", b"", {})

        handler = DeletionHandler(
            world.files,
            world.objects,
            QdrantVectorStore(Client(), "documents", "images"),
            stale_processing_seconds=900,
            clock=lambda: NOW,
            sleep=world.sleeps.append,
        )

        assert handler.handle(delete_body()) is Outcome.ACK
        assert world.files.docs[FILE_ID].status == "deleted"
        assert S3_KEY not in world.objects.objects
        assert FILE_ID not in world.files.pages
        assert world.sleeps == []
        assert world.events == [
            ("claim", FILE_ID),
            ("delete_object", S3_KEY),
            ("qdrant_delete", "documents"),
            ("qdrant_delete", "images"),
            ("delete_pages", FILE_ID),
            ("mark_deleted", FILE_ID),
        ]

    run(missing_images=False)
    run(missing_images=True)
