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
    "content_type",
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
    assert any(spec["name"] == "user_id_s3_key_active" for spec in files.indexes)
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
    assert body["content_type"] == "application/pdf"
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


def test_multipart_upload_rejects_docx_and_xlsx(stack) -> None:
    client, files, objects, publisher = stack
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    docx = upload(
        client,
        USER_A,
        content=b"PK\x03\x04docx",
        name="Отчёт.docx",
        content_type=docx_type,
    )
    xlsx = upload(
        client,
        USER_A,
        content=b"PK\x03\x04xlsx",
        name="Книга.xlsx",
        content_type=xlsx_type,
    )
    assert docx.status_code == 415
    assert xlsx.status_code == 415
    assert docx.json()["error"]["code"] == "unsupported_media_type"
    assert xlsx.json()["error"]["code"] == "unsupported_media_type"
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


def _manifest(**overrides) -> dict:
    body = {
        "s3_key": "incoming/user-photos/a.jpg",
        "file_name": "a.jpg",
        "content_sha256": "a" * 64,
        "file_size": 4,
        "content_type": "image/jpeg",
    }
    body.update(overrides)
    return body


def post_manifest(client, path, user_id, payload, headers=None):
    merged = auth(user_id)
    if headers:
        merged.update(headers)
    return client.post(path, headers=merged, json=payload)


def test_image_manifest_stores_row_and_publishes_without_uploading(stack) -> None:
    client, files, objects, publisher = stack
    payload = b"\xff\xd8\xff\xd9"
    key = "incoming/user-photos/a.jpg"
    objects.objects[key] = payload
    request_id = "22222222-2222-4222-8222-222222222222"
    response = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(
            s3_key=key,
            file_name="фото.jpg",
            file_size=len(payload),
            content_sha256="ab" * 32,
            content_type="image/jpeg",
        ),
        headers={"X-Request-Id": request_id},
    )
    assert response.status_code == 202
    assert response.headers["x-request-id"] == request_id
    body = response.json()
    assert set(body) == _CARD_KEYS
    assert body["content_type"] == "image/jpeg"
    assert body["file_name"] == "фото.jpg"
    assert body["file_size"] == len(payload)
    assert body["status"] == "uploaded"
    assert body["page_count"] is None
    assert body["error"] is None
    file_id = body["file_id"]
    stored = files.docs[file_id]
    assert stored["s3_key"] == key
    assert stored["content_sha256"] == "ab" * 32
    assert stored["file_size"] == len(payload)
    assert stored["content_type"] == "image/jpeg"
    assert stored["user_id"] == USER_A
    assert stored["file_name"] == "фото.jpg"
    assert stored["safe_name"] == "фото.jpg"
    assert stored["status"] == "uploaded"
    assert stored["page_count"] is None
    assert objects.puts == []
    assert objects.gets == 0
    assert objects.deletes == []
    assert objects.objects[key] == payload
    routing, message, props = publisher.messages[0]
    assert routing == "doc.process"
    assert message["s3_key"] == key
    assert message["content_type"] == "image/jpeg"
    assert message["file_id"] == file_id
    assert message["user_id"] == USER_A
    assert message["file_name"] == "фото.jpg"
    assert props["headers"]["x-request-id"] == request_id
    assert len(publisher.messages) == 1

    for index, (content_type, suffix) in enumerate(
        (
            ("image/png", "png"),
            ("image/webp", "webp"),
            ("image/gif", "gif"),
        ),
        start=1,
    ):
        image_key = f"incoming/user-photos/a.{suffix}"
        objects.objects[image_key] = payload
        accepted = post_manifest(
            client,
            "/api/files/images",
            USER_A,
            _manifest(
                s3_key=image_key,
                file_name=f"a.{suffix}",
                content_sha256=f"{index}" * 64,
                content_type=content_type,
            ),
        )
        assert accepted.status_code == 202
        assert accepted.json()["content_type"] == content_type
        assert accepted.json()["page_count"] is None
        published = publisher.messages[-1][1]
        assert published["s3_key"] == image_key
        assert published["content_type"] == content_type
    assert objects.puts == []


def test_document_manifest_accepts_pdf_and_keeps_caller_key(stack) -> None:
    client, files, objects, publisher = stack
    payload = b"%PDF-1.7\n"
    key = f"files/{USER_A.upper()}/batch/notes.pdf"
    objects.objects[key] = payload
    response = post_manifest(
        client,
        "/api/files/documents",
        USER_A,
        _manifest(
            s3_key=key,
            file_name="notes.txt",
            file_size=len(payload),
            content_sha256="d" * 64,
            content_type="application/pdf",
        ),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["content_type"] == "application/pdf"
    assert body["file_name"] == "notes.txt"
    assert body["status"] == "uploaded"
    assert body["page_count"] is None
    stored = files.docs[body["file_id"]]
    assert stored["s3_key"] == key
    assert stored["safe_name"] == "notes.pdf"
    assert stored["content_type"] == "application/pdf"
    assert stored["content_sha256"] == "d" * 64
    assert stored["user_id"] == USER_A
    assert objects.puts == []
    message = publisher.messages[0][1]
    assert message["content_type"] == "application/pdf"
    assert message["s3_key"] == key
    assert message["file_name"] == "notes.txt"


def test_document_manifest_rejects_text_and_image_types(stack) -> None:
    client, files, objects, publisher = stack
    for content_type in ("text/plain", "image/jpeg"):
        response = post_manifest(
            client,
            "/api/files/documents",
            USER_A,
            _manifest(content_type=content_type, content_sha256="e" * 64),
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"
    assert files.docs == {}
    assert objects.puts == []
    assert objects.heads == 0
    assert publisher.messages == []


def test_document_manifest_accepts_docx_and_xlsx(stack) -> None:
    client, files, objects, publisher = stack
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    samples = (
        (docx_type, "incoming/office/Отчёт.docx", "Отчёт.docx", "b" * 64),
        (xlsx_type, "incoming/office/Книга.xlsx", "Книга.xlsx", "c" * 64),
    )
    for content_type, key, file_name, digest in samples:
        payload = b"ooxml"
        objects.objects[key] = payload
        response = post_manifest(
            client,
            "/api/files/documents",
            USER_A,
            _manifest(
                s3_key=key,
                file_name=file_name,
                file_size=len(payload),
                content_sha256=digest,
                content_type=content_type,
            ),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["content_type"] == content_type
        assert body["file_name"] == file_name
        stored = files.docs[body["file_id"]]
        assert stored["content_type"] == content_type
        assert stored["s3_key"] == key
        assert stored["safe_name"] == file_name
        assert stored["content_sha256"] == digest
        routing, message, _props = publisher.messages[-1]
        assert routing == "doc.process"
        assert message["content_type"] == content_type
        assert message["s3_key"] == key
    assert objects.puts == []
    assert objects.gets == 0


def test_document_manifest_rejects_legacy_office_and_csv(stack) -> None:
    client, files, objects, publisher = stack
    rejected = (
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/csv",
    )
    for content_type in rejected:
        response = post_manifest(
            client,
            "/api/files/documents",
            USER_A,
            _manifest(content_type=content_type, content_sha256="f" * 64),
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"
    assert files.docs == {}
    assert objects.puts == []
    assert objects.heads == 0
    assert publisher.messages == []


def test_image_manifest_rejects_pdf(stack) -> None:
    client, files, objects, publisher = stack
    for content_type in ("application/pdf", "image/jpg", "text/plain"):
        response = post_manifest(
            client,
            "/api/files/images",
            USER_A,
            _manifest(content_type=content_type),
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"
    assert files.docs == {}
    assert publisher.messages == []
    assert objects.puts == []


def test_manifest_duplicate_hash_or_key_returns_existing_file_and_does_not_publish(stack) -> None:
    client, files, objects, publisher = stack
    payload = b"jpeg"
    first_key = "incoming/user-photos/a.jpg"
    second_key = "incoming/user-photos/b.jpg"
    objects.objects[first_key] = payload
    objects.objects[second_key] = payload
    digest = "a" * 64
    first = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=first_key, content_sha256=digest, file_size=len(payload)),
    )
    assert first.status_code == 202
    file_id = first.json()["file_id"]
    same_hash = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(
            s3_key=second_key,
            file_name="b.jpg",
            content_sha256=digest,
            file_size=len(payload),
        ),
    )
    assert same_hash.status_code == 409
    assert same_hash.json()["error"]["code"] == "duplicate_file"
    assert same_hash.json()["error"]["details"]["file_id"] == file_id
    assert len(publisher.messages) == 1
    assert set(files.docs) == {file_id}

    same_key = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(
            s3_key=first_key,
            file_name="again.jpg",
            content_sha256="b" * 64,
            file_size=len(payload),
        ),
    )
    assert same_key.status_code == 409
    assert same_key.json()["error"]["details"]["file_id"] == file_id
    assert len(publisher.messages) == 1
    assert set(files.docs) == {file_id}
    assert objects.puts == []
    assert objects.deletes == []
    assert objects.objects[first_key] == payload

    files.blind_lookups = 2
    third_key = "incoming/user-photos/c.jpg"
    objects.objects[third_key] = payload
    raced = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(
            s3_key=third_key,
            file_name="c.jpg",
            content_sha256=digest,
            file_size=len(payload),
        ),
    )
    assert raced.status_code == 409
    assert raced.json()["error"]["details"]["file_id"] == file_id
    assert set(files.docs) == {file_id}
    assert len(publisher.messages) == 1
    assert objects.deletes == []
    assert objects.objects[first_key] == payload

    files.docs[file_id]["status"] = "deleted"
    again = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=first_key, content_sha256=digest, file_size=len(payload)),
    )
    assert again.status_code == 202
    assert again.json()["file_id"] != file_id
    assert len(publisher.messages) == 2


def test_manifest_duplicate_prefers_s3_key_over_a_different_hash_match(stack) -> None:
    client, files, objects, publisher = stack
    hash_id = "11111111-1111-4111-8111-111111111111"
    key_id = "22222222-2222-4222-8222-222222222222"
    hash_key = "incoming/user-photos/by-hash.jpg"
    shared_key = "incoming/user-photos/by-key.jpg"
    objects.objects[shared_key] = b"jpeg"
    files.docs[hash_id] = {
        "file_id": hash_id,
        "user_id": USER_A,
        "file_name": "hash.jpg",
        "safe_name": "hash.jpg",
        "file_size": 4,
        "content_type": "image/jpeg",
        "content_sha256": "a" * 64,
        "s3_key": hash_key,
        "status": "ready",
        "page_count": None,
        "error": None,
        "delete_claimed_at": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    files.docs[key_id] = {
        **files.docs[hash_id],
        "file_id": key_id,
        "file_name": "key.jpg",
        "content_sha256": "b" * 64,
        "s3_key": shared_key,
    }
    response = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=shared_key, content_sha256="a" * 64, file_size=4, file_name="again.jpg"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["file_id"] == key_id
    assert set(files.docs) == {hash_id, key_id}
    assert publisher.messages == []

    files.blind_lookups = 2
    raced = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=shared_key, content_sha256="c" * 64, file_size=4, file_name="race.jpg"),
    )
    assert raced.status_code == 409
    assert raced.json()["error"]["details"]["file_id"] == key_id
    assert set(files.docs) == {hash_id, key_id}
    assert publisher.messages == []


def test_manifest_missing_object_and_foreign_prefix_are_404(stack) -> None:
    client, files, objects, publisher = stack
    missing = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key="incoming/user-photos/missing.jpg"),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "object_not_found"
    assert "details" not in missing.json()["error"]

    foreign_key = f"files/{USER_B}/photo.jpg"
    objects.objects[foreign_key] = b"jpeg"
    foreign = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=foreign_key, file_size=4, content_sha256="c" * 64),
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "object_not_found"
    assert files.docs == {}
    assert publisher.messages == []
    assert objects.puts == []


def test_manifest_size_mismatch_is_400_and_omitted_head_size_is_trusted(stack) -> None:
    client, files, objects, publisher = stack
    key = "incoming/user-photos/a.jpg"
    objects.objects[key] = b"abcd"
    mismatch = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=key, file_size=12345),
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "validation_error"
    assert mismatch.json()["error"]["details"]["fields"] == ["file_size"]
    assert files.docs == {}
    assert publisher.messages == []

    objects.head_sizes[key] = None
    trusted = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(s3_key=key, file_size=12345, content_sha256="9" * 64),
    )
    assert trusted.status_code == 202
    assert trusted.json()["file_size"] == 12345
    assert files.docs[trusted.json()["file_id"]]["file_size"] == 12345


def test_manifest_rejects_unsafe_keys_and_bad_fields(stack) -> None:
    client, files, objects, publisher = stack
    objects.objects["incoming/user-photos/a.jpg"] = b"jpeg"
    cases = (
        {"s3_key": "/incoming/a.jpg"},
        {"s3_key": "incoming/../a.jpg"},
        {"s3_key": "incoming\\a.jpg"},
        {"s3_key": ""},
        {"s3_key": "a..b.jpg"},
        {"file_size": 0},
        {"file_size": True},
        {"content_sha256": "A" * 64},
        {"content_sha256": "ab"},
        {"file_name": ".."},
        {"file_name": "a" * 256},
    )
    for override in cases:
        response = post_manifest(client, "/api/files/images", USER_A, _manifest(**override))
        assert response.status_code == 400, override
        assert response.json()["error"]["code"] == "validation_error"
    assert files.docs == {}
    assert publisher.messages == []
    assert objects.puts == []


def test_image_content_uses_stored_content_type_and_s3_key(stack) -> None:
    client, files, objects, _publisher = stack
    payload = b"\xff\xd8\xff\xd9fake-jpeg"
    key = "incoming/user-photos/a.jpg"
    objects.objects[key] = payload
    created = post_manifest(
        client,
        "/api/files/images",
        USER_A,
        _manifest(
            s3_key=key,
            file_name="a.jpg",
            file_size=len(payload),
            content_type="image/png",
            content_sha256="1" * 64,
        ),
    )
    assert created.status_code == 202
    file_id = created.json()["file_id"]
    assert created.json()["content_type"] == "image/png"
    own = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert own.status_code == 200
    assert own.headers["content-type"] == "image/png"
    assert own.content == payload
    assert own.headers["content-length"] == str(len(payload))
    card = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert card.status_code == 200
    assert card.json()["content_type"] == "image/png"
    listed = client.get("/api/files", headers=auth(USER_A))
    assert listed.json()["items"][0]["content_type"] == "image/png"
    assert files.docs[file_id]["s3_key"] == key


def test_file_card_includes_content_type_for_pdf_upload(stack) -> None:
    client, _files, _objects, _publisher = stack
    created = upload(client, USER_A)
    assert created.status_code == 202
    assert created.json()["content_type"] == "application/pdf"
    file_id = created.json()["file_id"]
    card = client.get(f"/api/files/{file_id}", headers=auth(USER_A))
    assert card.json()["content_type"] == "application/pdf"
    listed = client.get("/api/files", headers=auth(USER_A))
    assert listed.json()["items"][0]["content_type"] == "application/pdf"


def test_static_file_routes_are_not_parsed_as_file_ids(stack) -> None:
    client, _files, _objects, _publisher = stack
    for path in ("/api/files/images", "/api/files/documents"):
        fetched = client.get(path, headers=auth(USER_A))
        assert fetched.status_code == 400
        assert fetched.json()["error"]["details"]["fields"] == ["file_id"]
        deleted = client.delete(path, headers=auth(USER_A))
        assert deleted.status_code == 400
        assert deleted.json()["error"]["details"]["fields"] == ["file_id"]
    missing = client.get("/api/files/not-a-uuid", headers=auth(USER_A))
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "validation_error"


def test_manifest_auth_matches_other_file_routes(stack) -> None:
    client, files, objects, publisher = stack
    objects.objects["incoming/user-photos/a.jpg"] = b"jpeg"
    anonymous = client.post("/api/files/images", json=_manifest())
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "unauthenticated"
    blocked = post_manifest(
        client,
        "/api/files/documents",
        USER_A,
        _manifest(content_type="application/pdf"),
        headers={"X-Auth-Role": "BLOCKED"},
    )
    assert blocked.status_code == 403
    assert files.docs == {}
    assert publisher.messages == []


def test_manifest_publish_failure_marks_enqueue_failed(stack) -> None:
    client, files, objects, publisher = stack
    objects.objects["incoming/user-photos/a.jpg"] = b"jpeg"
    publisher.remaining_failures = 1
    response = post_manifest(client, "/api/files/images", USER_A, _manifest())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "enqueue_failed"
    document = next(iter(files.docs.values()))
    assert document["status"] == "error"
    assert document["error"] == "enqueue_failed"
    assert publisher.messages == []


def test_manifest_head_failure_is_503(stack) -> None:
    client, files, objects, publisher = stack
    objects.objects["incoming/user-photos/a.jpg"] = b"jpeg"
    objects.fail_head = True
    response = post_manifest(client, "/api/files/images", USER_A, _manifest())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert files.docs == {}
    assert publisher.messages == []


def test_content_dependency_failure_is_503(stack) -> None:
    client, files, objects, _publisher = stack
    created = upload(client, USER_A)
    file_id = created.json()["file_id"]
    objects.fail_get = True
    response = client.get(f"/api/files/{file_id}/content", headers=auth(USER_A))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    assert files.docs[file_id]["status"] == "uploaded"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
GIF = b"GIF89a" + b"\x00" * 24
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


def upload_image(
    client,
    user_id,
    content=PNG,
    name="photo.png",
    content_type="image/png",
):
    return client.post(
        "/api/files/images",
        headers=auth(user_id),
        files={"file": (name, content, content_type)},
    )


def test_image_multipart_upload_stores_bytes_and_publishes_content_type(stack) -> None:
    client, files, objects, publisher = stack
    response = upload_image(client, USER_A, name="photo.png")
    assert response.status_code == 202
    card = response.json()
    assert card["content_type"] == "image/png"
    assert card["page_count"] is None
    assert card["status"] == "uploaded"
    document = files.docs[card["file_id"]]
    assert document["s3_key"] == f"files/{USER_A}/{card['file_id']}/photo.png"
    assert objects.objects[document["s3_key"]] == PNG
    assert len(publisher.messages) == 1
    routing_key, body, _properties = publisher.messages[0]
    assert routing_key == "doc.process"
    assert body["content_type"] == "image/png"
    assert body["s3_key"] == document["s3_key"]


def test_image_multipart_detects_each_type_from_bytes(stack) -> None:
    client, _files, _objects, publisher = stack
    cases = (
        (PNG, "a.png", "image/png"),
        (JPEG, "b.jpg", "image/jpeg"),
        (WEBP, "c.webp", "image/webp"),
        (GIF, "d.gif", "image/gif"),
    )
    for content, name, expected in cases:
        response = upload_image(client, USER_A, content=content, name=name)
        assert response.status_code == 202, response.text
        assert response.json()["content_type"] == expected
    published = [body["content_type"] for _key, body, _properties in publisher.messages]
    assert published == [expected for _content, _name, expected in cases]


def test_image_multipart_rejects_bytes_that_are_not_an_image(stack) -> None:
    client, files, objects, publisher = stack
    for content, declared in (
        (PDF, "application/pdf"),
        (b"%PDF-1.4\n", "image/png"),
        (b"not an image", "image/png"),
        (b"", "image/png"),
    ):
        response = upload_image(client, USER_A, content=content, content_type=declared)
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"
    assert files.docs == {}
    assert objects.puts == []
    assert publisher.messages == []


def test_document_multipart_still_rejects_image_bytes(stack) -> None:
    client, files, objects, publisher = stack
    response = upload(client, USER_A, content=PNG, name="photo.png", content_type="image/png")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert files.docs == {}
    assert objects.puts == []
    assert publisher.messages == []


def test_image_multipart_size_limit_is_413(stack) -> None:
    app, _files, objects, publisher = build_app(max_upload_bytes=len(PNG) - 1)
    with TestClient(app) as client:
        response = upload_image(client, USER_A)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert objects.puts == []
    assert publisher.messages == []


def test_image_multipart_duplicate_is_409(stack) -> None:
    client, _files, objects, publisher = stack
    first = upload_image(client, USER_A, name="one.png")
    assert first.status_code == 202
    again = upload_image(client, USER_A, name="two.png")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "duplicate_file"
    assert again.json()["error"]["details"]["file_id"] == first.json()["file_id"]
    assert len(objects.objects) == 1
    assert len(publisher.messages) == 1
