from __future__ import annotations

from tests.support import make_settings

from processor.mongo_store import MongoFiles


def test_ensure_indexes_creates_the_shared_s3_key_index() -> None:
    class Collection:
        def __init__(self) -> None:
            self.calls: list[tuple[list, dict]] = []

        def create_index(self, keys, **kwargs):
            self.calls.append((list(keys), dict(kwargs)))
            return "ok"

    class Database:
        def __init__(self) -> None:
            self.collections = {"files": Collection(), "file_pages": Collection()}

        def __getitem__(self, name: str) -> Collection:
            return self.collections[name]

    class Client:
        def __init__(self) -> None:
            self.database = Database()

        def get_default_database(self) -> Database:
            return self.database

    client = Client()
    MongoFiles(make_settings(), client=client).ensure_indexes()  # type: ignore[arg-type]
    files = client.database.collections["files"].calls
    assert files[-1] == (
        [("user_id", 1), ("s3_key", 1)],
        {
            "unique": True,
            "partialFilterExpression": {"status": {"$in": ["uploaded", "processing", "ready", "error", "deleting"]}},
            "name": "user_id_s3_key_active",
        },
    )
    assert client.database.collections["file_pages"].calls[0][1]["name"] == "file_id_page_number"
