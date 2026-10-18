import json
from datetime import UTC, datetime, timedelta

import httpx

from chat.app import create_app
from chat.config import Settings
from chat.embedding import EmbeddingClient
from chat.llm import LLMClient
from chat.repository import FileRecord
from tests.memory import MemoryQdrant, MemoryRepository
from tests.transport import ScriptedTransport

USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
FILE_A = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f"
FILE_B = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
NOT_FOUND = "Не найдено в документах."


class StepClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "mongodb_uri": "mongodb://localhost:27017/rag",
        "qdrant_url": "http://qdrant:6333",
        "qdrant_collection": "documents",
        "embedding_url": "http://embedding:8091",
        "llm_base_url": "http://llm:4000/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "llm_temperature": 0.2,
        "llm_timeout_seconds": 60.0,
        "rag_top_k": 5,
        "rag_min_score": 0.0,
        "rag_context_messages": 10,
        "embedding_timeout": 10.0,
        "embedding_dim": 768,
        "embedding_max_tokens": 1024,
        "chat_port": 8082,
        "log_level": "info",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class World:
    def __init__(self, settings: Settings | None = None, **overrides: object) -> None:
        self.settings = settings or make_settings(**overrides)
        self.repo = MemoryRepository()
        self.vectors = MemoryQdrant()
        self.transport = ScriptedTransport(dim=self.settings.embedding_dim)
        self.embedder = EmbeddingClient(self.settings, transport=self.transport)
        self.llm = LLMClient(self.settings, transport=self.transport)
        self.clock = StepClock()
        self.app = create_app(
            self.settings,
            repo=self.repo,
            vectors=self.vectors,
            embedder=self.embedder,
            llm=self.llm,
            clock=self.clock,
        )

    def add_file(
        self,
        *,
        user_id: str,
        file_id: str,
        file_name: str,
        status: str = "ready",
    ) -> None:
        self.repo.files.append(
            FileRecord(file_id=file_id, user_id=user_id, file_name=file_name, status=status)
        )

    def add_point(
        self,
        *,
        user_id: str,
        document_id: str,
        text: str,
        page_number: int,
        chunk_index: int = 0,
        score: float = 0.9,
    ) -> None:
        from tests.memory import StoredPoint

        self.vectors.points.append(
            StoredPoint(
                user_id=user_id,
                document_id=document_id,
                text=text,
                page_number=page_number,
                chunk_index=chunk_index,
                score=score,
            )
        )


def parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.decode().split("\n\n"):
        if not block.strip():
            continue
        event_name = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        if event_name is None or data is None:
            raise AssertionError(f"malformed SSE block: {block!r}")
        events.append((event_name, data))
    return events


def auth(user_id: str, **extra: str) -> dict[str, str]:
    return {"X-Auth-User-Id": user_id, **extra}


async def open_client(world: World) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=world.app)
    return httpx.AsyncClient(transport=transport, base_url="http://chat")
