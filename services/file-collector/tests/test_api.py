import hashlib
import re
from datetime import timedelta

from fastapi.testclient import TestClient
from file_collector.clock import utcnow
from tests.support import PDF, USER_A, USER_B, build_app

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CARD_KEYS = {
    "file_id",
    "file_name",
    "file_size",
    "status",
    "page_count",
    "error",
    "progress",
    "created_at",
    "updated_at",
}


def auth(user_id: str, **extra: str) -> dict[str, str]:
    headers = {"X-Auth-User-Id": user_id}
    headers.update(extra)
    return headers


def upload(
    client,
    user_id,
    content=PDF,
    name="note.pdf",
    content_type="application/pdf",
    headers=None,
):
    merged = auth(user_id)
    if headers:
        merged.update(headers)
    return client.post(
        "/api/files",
        headers=merged,
        files={"file": (name, content, content_type)},
    )


def test_health_does_not_touch_dependencies(stack) -> None:
    client, files, objects, publisher = stack
    reads = files.reads
    gets = objects.gets
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert files.reads == reads
    assert objects.gets == gets
    blocked = client.get("/health", headers={"X-Auth-Role": "BLOCKED"})
    assert blocked.status_code == 200
    assert files.indexes is not None
    assert objects.bucket is True
    assert publisher.topology_ready is True
    assert publisher.connected is True


def test_request_id_is_echoed_or_generated(stack) -> None:
    client, _files, _objects, _publisher = stack
    given = "12345678-1234-4234-8234-123456789abc"
    echoed = client.get("/health", headers={"X-Request-Id": given})
    assert echoed.headers["x-request-id"] == given
    generated = client.get("/health", headers={"X-Request-Id": "not-a-uuid"})
    assert _UUID.fullmatch(generated.headers["x-request-id"])
    assert generated.headers["x-request-id"] != "not-a-uuid"


def test_missing_auth_is_401_and_x_user_id_is_ignored(stack) -> None:
    client, files, _objects, publisher = stack
    missing = client.get("/api/files")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthenticated"
    assert missing.json()["error"]["message"] == "Missing or invalid X-Auth-User-Id"

    only_user = client.get("/api/files", headers={"X-User-Id": USER_A})
    assert only_user.status_code == 401
    assert only_user.json()["error"]["code"] == "unauthenticated"

    invalid = client.get("/api/files", headers={"X-Auth-User-Id": "not-a-uuid"})
    assert invalid.status_code == 401

    posted = upload(client, USER_A, headers={"X-User-Id": USER_B})
    assert posted.status_code == 202
    file_id = posted.json()["file_id"]
    assert files.docs[file_id]["user_id"] == USER_A
    foreign = client.get("/api/files", headers=auth(USER_B))
    assert foreign.status_code == 200
    assert foreign.json()["total"] == 0
    own = client.get("/api/files", headers=auth(USER_A.upper()))
    assert own.json()["total"] == 1
    assert publisher.messages[0][1]["user_id"] == USER_A


def test_blocked_role_is_403_and_stores_nothing(stack) -> None:
    client, files, objects, publisher = stack
    response = upload(client, USER_A, headers={"X-Auth-Role": "BLOCKED"})
    assert response.status_code == 403
    assert response.json()["error"] == {"code": "forbidden", "message": "User is blocked"}
    assert files.docs == {}
    assert objects.objects == {}
    assert publisher.messages == []
    listed = client.get("/api/files", headers=auth(USER_A, **{"X-Auth-Role": "BLOCKED"}))
    assert listed.status_code == 403


def test_upload_stores_metadata_and_publishes_doc_process(stack) -> None:
    client, files, objects, publisher = stack
    request_id = "11111111-1111-4111-8111-111111111111"
    response = upload(
        client,
        USER_A,
        name="my report.pdf",
        headers={"X-Request-Id": request_id},
    )
    assert response.status_code == 202
    assert response.headers["x-request-id"] == request_id
    body = response.json()
    assert set(body) == _CARD_KEYS
    assert body["file_name"] == "my report.pdf"
    assert body["file_size"] == len(PDF)
    assert body["status"] == "uploaded"
    assert body["page_count"] is None
    assert body["error"] is None
    assert body["progress"] is None
    assert body["created_at"] == body["updated_at"]
    assert body["created_at"].endswith("Z")
    file_id = body["file_id"]
    assert _UUID.fullmatch(file_id)
    stored = files.docs[file_id]
    assert stored["s3_key"] == f"files/{USER_A}/{file_id}/my_report.pdf"
    assert stored["content_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert stored["content_type"] == "application/pdf"
    assert stored["delete_claimed_at"] is None
    assert stored["safe_name"] == "my_report.pdf"
    assert objects.objects[stored["s3_key"]] == PDF
    assert "s3_key" not in body
    assert "user_id" not in body
    assert "content_sha256" not in body
    routing, message, props = publisher.messages[0]
    assert routing == "doc.process"
    assert message["schema_version"] == 1
    assert message["message_type"] == "doc.process"
    assert message["file_id"] == file_id
    assert message["user_id"] == USER_A
    assert message["s3_key"] == stored["s3_key"]
    assert message["file_name"] == "my report.pdf"
    assert message["content_type"] == "application/pdf"
    assert props["delivery_mode"] == 2
    assert props["content_type"] == "application/json"
    assert props["content_encoding"] == "utf-8"
    assert props["app_id"] == "file-collector"
    assert props["message_id"] == message["message_id"]
    assert props["headers"]["x-request-id"] == request_id
    assert isinstance(props["timestamp"], int)


def test_file_too_large_is_413_and_writes_nothing() -> None:
    limit = 16
    app, files, objects, publisher = build_app(max_upload_bytes=limit)
    payload = b"%PDF-1.4\n" + b"B" * 32
    assert len(payload) > limit
    with TestClient(app) as client:
        response = upload(client, USER_A, content=payload)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert files.docs == {}
    assert objects.objects == {}
    assert objects.puts == []
    assert publisher.messages == []


def test_upload_at_the_size_limit_is_accepted() -> None:
    payload = b"%PDF-1.4\n" + b"A" * 7
    app, files, _objects, _publisher = build_app(max_upload_bytes=len(payload))
    with TestClient(app) as client:
        response = upload(client, USER_A, content=payload)
    assert response.status_code == 202
    assert len(files.docs) == 1


def test_non_pdf_is_415_even_with_pdf_content_type(stack) -> None:
    client, files, objects, publisher = stack
    response = upload(client, USER_A, content=b"not a pdf", content_type="application/pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    lowercase = upload(client, USER_A, content=b"%pdf-1.4\n")
    assert lowercase.status_code == 415
    empty = upload(client, USER_A, content=b"")
    assert empty.status_code == 415
    assert files.docs == {}
    assert objects.puts == []
    assert publisher.messages == []


def test_duplicate_returns_409_with_file_id_and_reupload_after_deleted(stack) -> None:
    client, files, objects, _publisher = stack
    first = upload(client, USER_A, name="first.pdf")
    assert first.status_code == 202
    file_id = first.json()["file_id"]
    second = upload(client, USER_A, name="second.pdf")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_file"
    assert second.json()["error"]["details"]["file_id"] == file_id
    assert len(files.docs) == 1
    assert len(objects.objects) == 1

    other = upload(client, USER_B)
    assert other.status_code == 202
    assert other.json()["file_id"] != file_id

    files.docs[file_id]["status"] = "deleted"
    again = upload(client, USER_A, name="again.pdf")
    assert again.status_code == 202
    new_id = again.json()["file_id"]
    assert new_id != file_id
    listed = client.get("/api/files", headers=auth(USER_A))
    ids = [item["file_id"] for item in listed.json()["items"]]
    assert file_id not in ids
    assert new_id in ids


def test_duplicate_index_conflict_removes_the_new_object(stack) -> None:
    client, files, objects, _publisher = stack
    first = upload(client, USER_A)
    file_id = first.json()["file_id"]
    files.blind_lookups = 1
    raced = upload(client, USER_A, name="race.pdf")
    assert raced.status_code == 409
    assert raced.json()["error"]["details"]["file_id"] == file_id
    assert set(files.docs) == {file_id}
    assert set(objects.objects) == {files.docs[file_id]["s3_key"]}
    assert len(objects.deletes) == 1


def test_list_hides_deleted_and_other_users(stack) -> None:
    client, files, _objects, _publisher = stack
    own = upload(client, USER_A, name="own.pdf")
    other = upload(client, USER_B, name="other.pdf", content=b"%PDF-other\n")
    deleted = upload(client, USER_A, name="gone.pdf", content=b"%PDF-gone\n")
    files.docs[deleted.json()["file_id"]]["status"] = "deleted"
    files.docs[own.json()["file_id"]]["created_at"] = utcnow() - timedelta(hours=1)
    response = client.get("/api/files", headers=auth(USER_A))
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] == 1
    assert [item["file_id"] for item in body["items"]] == [own.json()["file_id"]]
    assert other.json()["file_id"] not in {item["file_id"] for item in body["items"]}
    foreign = client.get("/api/files", headers=auth(USER_B))
    assert [item["file_id"] for item in foreign.json()["items"]] == [other.json()["file_id"]]


def test_list_pagination_and_invalid_query(stack) -> None:
    client, files, _objects, _publisher = stack
    older = upload(client, USER_A, name="older.pdf")
    newer = upload(client, USER_A, name="newer.pdf", content=b"%PDF-newer\n")
    files.docs[older.json()["file_id"]]["created_at"] = utcnow() - timedelta(days=1)
    page = client.get("/api/files?limit=1&offset=0", headers=auth(USER_A))
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert [item["file_id"] for item in page.json()["items"]] == [newer.json()["file_id"]]
    second = client.get("/api/files?limit=1&offset=1", headers=auth(USER_A))
    assert [item["file_id"] for item in second.json()["items"]] == [older.json()["file_id"]]
    invalid = client.get("/api/files?limit=0&offset=-1", headers=auth(USER_A))
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["details"]["fields"] == ["limit", "offset"]
    too_big = client.get("/api/files?limit=101", headers=auth(USER_A))
    assert too_big.status_code == 400


def test_progress_pages_done_is_exposed_only_while_processing(stack) -> None:
    client, files, _objects, _publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    document = files.docs[file_id]
    document["status"] = "processing"
    document["page_count"] = 8
    document["checkpoint"] = {
        "pages_done": 3,
        "pages_total": 8,
        "chunks_done": 1,
        "chunks_total": None,
    }
    card = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert card.status_code == 200
    assert card.json()["progress"] == {
        "pages_done": 3,
        "pages_total": 8,
        "chunks_done": 1,
        "chunks_total": None,
    }
    assert card.json()["page_count"] == 8
    listed = client.get("/api/files", headers=auth(USER_A))
    assert listed.json()["items"][0]["progress"]["pages_done"] == 3
    document["status"] = "ready"
    ready = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert ready.json()["progress"] is None
    assert ready.json()["status"] == "ready"


def test_content_404_for_other_user_or_deleted_and_bytes_for_ready(stack) -> None:
    client, files, _objects, _publisher = stack
    created = upload(client, USER_A, name="Отчёт.pdf")
    file_id = created.json()["file_id"]
    files.docs[file_id]["status"] = "ready"
    own = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert own.status_code == 200
    assert own.headers["content-type"] == "application/pdf"
    assert own.content == PDF
    assert own.headers["content-length"] == str(len(PDF))
    disposition = own.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert "filename*=UTF-8''" in disposition
    assert own.content.startswith(b"%PDF")

    foreign = client.get(f"/api/files/{file_id}/content", headers=auth(USER_B))
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "file_not_found"
    foreign_card = client.get(f"/api/files/{file_id}", headers=auth(USER_B))
    assert foreign_card.status_code == 404

    files.docs[file_id]["status"] = "deleted"
    deleted = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert deleted.status_code == 404
    deleted_card = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert deleted_card.status_code == 404

    files.docs[file_id]["status"] = "deleting"
    deleting = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert deleting.status_code == 404
    deleting_card = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert deleting_card.status_code == 200
    assert deleting_card.json()["status"] == "deleting"


def test_delete_while_processing_is_409_and_ready_enqueues_doc_delete(stack) -> None:
    client, files, _objects, publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    document = files.docs[file_id]
    document["status"] = "processing"
    document["updated_at"] = utcnow()
    busy = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "file_busy"
    assert busy.json()["error"]["message"] == "File cannot be deleted in its current state"
    assert files.docs[file_id]["status"] == "processing"
    assert not any(item[0] == "doc.delete" for item in publisher.messages)

    document["status"] = "ready"
    accepted = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert accepted.status_code == 202
    assert accepted.json() == {"file_id": file_id, "status": "deleting"}
    assert files.docs[file_id]["status"] == "deleting"
    routing, body, props = publisher.messages[-1]
    assert routing == "doc.delete"
    assert set(body) == {
        "schema_version",
        "message_type",
        "message_id",
        "file_id",
        "user_id",
        "s3_key",
        "created_at",
    }
    assert body["message_type"] == "doc.delete"
    assert body["file_id"] == file_id
    assert body["user_id"] == USER_A
    assert body["s3_key"] == document["s3_key"]
    assert props["app_id"] == "file-collector"
    assert props["delivery_mode"] == 2
    repeat = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "file_busy"


def test_stale_processing_can_be_deleted(stack) -> None:
    client, files, _objects, publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    document = files.docs[file_id]
    document["status"] = "processing"
    document["updated_at"] = utcnow() - timedelta(seconds=901)
    response = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert response.status_code == 202
    assert files.docs[file_id]["status"] == "deleting"
    assert publisher.messages[-1][0] == "doc.delete"


def test_delete_of_other_user_or_deleted_is_404(stack) -> None:
    client, files, _objects, publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    foreign = client.delete(f"/api/files/{file_id}", headers=auth(USER_B))
    assert foreign.status_code == 404
    assert files.docs[file_id]["status"] == "uploaded"
    files.docs[file_id]["status"] = "deleted"
    missing = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert missing.status_code == 404
    assert not any(item[0] == "doc.delete" for item in publisher.messages)


def test_enqueue_failure_marks_error_and_file_stays_deletable(stack) -> None:
    client, files, _objects, publisher = stack
    publisher.remaining_failures = 1
    response = upload(client, USER_A)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "enqueue_failed"
    assert len(files.docs) == 1
    document = next(iter(files.docs.values()))
    assert document["status"] == "error"
    assert document["error"] == "enqueue_failed"
    listed = client.get("/api/files", headers=auth(USER_A))
    assert listed.json()["items"][0]["status"] == "error"
    assert listed.json()["items"][0]["error"] == "enqueue_failed"
    assert listed.json()["items"][0]["progress"] is None
    deleted = client.delete(f"/api/files/{document['file_id']}", headers=auth(USER_A))
    assert deleted.status_code == 202
    assert publisher.messages[-1][0] == "doc.delete"


def test_delete_publish_failure_stays_deleting_and_repeat_is_busy(stack) -> None:
    client, files, _objects, publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    publisher.fail = True
    failed = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "enqueue_failed"
    assert files.docs[file_id]["status"] == "deleting"
    again = client.delete(f"/api/files/{file_id}", headers=auth(USER_A))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "file_busy"


def test_storage_failure_on_upload_leaves_no_metadata(stack) -> None:
    client, files, objects, publisher = stack
    objects.fail_put = True
    response = upload(client, USER_A)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert files.docs == {}
    assert objects.objects == {}
    assert publisher.messages == []

    objects.fail_put = False
    files.fail_insert = True
    failed_insert = upload(client, USER_A)
    assert failed_insert.status_code == 503
    assert files.docs == {}
    assert objects.objects == {}
    assert objects.puts
    assert objects.deletes


def test_bad_filename_is_400(stack) -> None:
    client, files, objects, _publisher = stack
    response = upload(client, USER_A, name="a" * 256)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert files.docs == {}
    assert objects.puts == []
    nested = upload(client, USER_A, name="../../secret.pdf")
    assert nested.status_code == 202
    assert nested.json()["file_name"] == "secret.pdf"


def test_content_dependency_failure_is_503(stack) -> None:
    client, files, objects, _publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    objects.fail_get = True
    response = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert files.docs[file_id]["status"] == "uploaded"
