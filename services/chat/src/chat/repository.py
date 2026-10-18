import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from chat.config import Settings
from chat.errors import DependencyUnavailable
from chat.textutil import DEFAULT_TITLE

logger = logging.getLogger("chat")


@dataclass(slots=True)
class ChatRecord:
    chat_id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class MessageRecord:
    message_id: str
    chat_id: str
    user_id: str
    role: str
    content: str
    created_at: datetime
    sources: list[dict[str, object]] | None = None


@dataclass(slots=True)
class FileRecord:
    file_id: str
    user_id: str
    file_name: str
    status: str


@dataclass(slots=True)
class Turn:
    chat_id: str
    user_id: str
    user_message_id: str
    assistant_message_id: str
    question: str
    answer: str
    sources: list[dict[str, object]]
    user_created_at: datetime
    assistant_created_at: datetime
    title: str


class ChatRepository(Protocol):
    async def ensure_indexes(self) -> None: ...

    async def create_chat(self, user_id: str, title: str, now: datetime) -> ChatRecord: ...

    async def list_chats(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[ChatRecord], int]: ...

    async def get_chat(self, user_id: str, chat_id: str) -> ChatRecord | None: ...

    async def delete_chat(self, user_id: str, chat_id: str) -> bool: ...

    async def list_messages(
        self, user_id: str, chat_id: str, limit: int, offset: int
    ) -> tuple[list[MessageRecord], int]: ...

    async def recent_messages(
        self, user_id: str, chat_id: str, limit: int
    ) -> list[MessageRecord]: ...

    async def ready_files(self, user_id: str, file_ids: list[str]) -> dict[str, FileRecord]: ...

    async def save_turn(self, turn: Turn) -> None: ...

    async def close(self) -> None: ...


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MongoChatRepository:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
        self._db = self._client.get_default_database(default="rag")
        self._chats = self._db["chats"]
        self._messages = self._db["messages"]
        self._files = self._db["files"]

    @asynccontextmanager
    async def _guard(self):
        try:
            yield
        except PyMongoError as exc:
            logger.warning("mongodb error: %s", type(exc).__name__)
            raise DependencyUnavailable() from exc

    async def ensure_indexes(self) -> None:
        async with self._guard():
            await self._chats.create_index("chat_id", unique=True, name="chat_id_unique")
            await self._chats.create_index(
                [("user_id", 1), ("updated_at", -1)],
                name="user_updated_at",
            )
            await self._messages.create_index("message_id", unique=True, name="message_id_unique")
            await self._messages.create_index(
                [("chat_id", 1), ("created_at", 1)],
                name="chat_created_at",
            )
            await self._messages.create_index(
                [("user_id", 1), ("created_at", -1)],
                name="user_created_at",
            )

    async def create_chat(self, user_id: str, title: str, now: datetime) -> ChatRecord:
        from uuid import uuid4

        chat_id = str(uuid4())
        document = {
            "chat_id": chat_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        async with self._guard():
            await self._chats.insert_one(document)
        return ChatRecord(
            chat_id=chat_id,
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )

    async def list_chats(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[ChatRecord], int]:
        query = {"user_id": user_id}
        async with self._guard():
            total = await self._chats.count_documents(query)
            cursor = self._chats.find(query).sort("updated_at", -1).skip(offset).limit(limit)
            documents = await cursor.to_list(length=limit)
        return [self._chat_from(document) for document in documents], int(total)

    async def get_chat(self, user_id: str, chat_id: str) -> ChatRecord | None:
        async with self._guard():
            document = await self._chats.find_one({"chat_id": chat_id, "user_id": user_id})
        if document is None:
            return None
        return self._chat_from(document)

    async def delete_chat(self, user_id: str, chat_id: str) -> bool:
        async with self._guard():
            document = await self._chats.find_one({"chat_id": chat_id, "user_id": user_id})
            if document is None:
                return False
            await self._messages.delete_many({"chat_id": chat_id, "user_id": user_id})
            await self._chats.delete_one({"chat_id": chat_id, "user_id": user_id})
        return True

    async def list_messages(
        self, user_id: str, chat_id: str, limit: int, offset: int
    ) -> tuple[list[MessageRecord], int]:
        query = {"chat_id": chat_id, "user_id": user_id}
        async with self._guard():
            total = await self._messages.count_documents(query)
            cursor = self._messages.find(query).sort("created_at", 1).skip(offset).limit(limit)
            documents = await cursor.to_list(length=limit)
        return [self._message_from(document) for document in documents], int(total)

    async def recent_messages(self, user_id: str, chat_id: str, limit: int) -> list[MessageRecord]:
        if limit <= 0:
            return []
        query = {"chat_id": chat_id, "user_id": user_id}
        async with self._guard():
            cursor = self._messages.find(query).sort("created_at", -1).limit(limit)
            documents = await cursor.to_list(length=limit)
        records = [self._message_from(document) for document in documents]
        records.reverse()
        return records

    async def ready_files(self, user_id: str, file_ids: list[str]) -> dict[str, FileRecord]:
        if not file_ids:
            return {}
        query = {"file_id": {"$in": file_ids}, "user_id": user_id, "status": "ready"}
        async with self._guard():
            cursor = self._files.find(query)
            documents = await cursor.to_list(length=len(file_ids))
        found: dict[str, FileRecord] = {}
        for document in documents:
            record = FileRecord(
                file_id=str(document["file_id"]),
                user_id=str(document["user_id"]),
                file_name=str(document["file_name"]),
                status=str(document["status"]),
            )
            found[record.file_id] = record
        return found

    async def save_turn(self, turn: Turn) -> None:
        user_doc = {
            "message_id": turn.user_message_id,
            "chat_id": turn.chat_id,
            "user_id": turn.user_id,
            "role": "user",
            "content": turn.question,
            "created_at": turn.user_created_at,
        }
        assistant_doc = {
            "message_id": turn.assistant_message_id,
            "chat_id": turn.chat_id,
            "user_id": turn.user_id,
            "role": "assistant",
            "content": turn.answer,
            "sources": turn.sources,
            "created_at": turn.assistant_created_at,
        }
        async with self._guard():
            await self._messages.insert_one(user_doc)
            await self._messages.insert_one(assistant_doc)
            renamed = await self._chats.update_one(
                {"chat_id": turn.chat_id, "user_id": turn.user_id, "title": DEFAULT_TITLE},
                {"$set": {"title": turn.title, "updated_at": turn.assistant_created_at}},
            )
            if renamed.matched_count == 0:
                await self._chats.update_one(
                    {"chat_id": turn.chat_id, "user_id": turn.user_id},
                    {"$set": {"updated_at": turn.assistant_created_at}},
                )

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _chat_from(document: dict) -> ChatRecord:
        return ChatRecord(
            chat_id=str(document["chat_id"]),
            user_id=str(document["user_id"]),
            title=str(document["title"]),
            created_at=_aware(document["created_at"]),
            updated_at=_aware(document["updated_at"]),
        )

    @staticmethod
    def _message_from(document: dict) -> MessageRecord:
        sources = document.get("sources")
        if document.get("role") != "assistant":
            sources = None
        elif sources is None:
            sources = []
        return MessageRecord(
            message_id=str(document["message_id"]),
            chat_id=str(document["chat_id"]),
            user_id=str(document["user_id"]),
            role=str(document["role"]),
            content=str(document["content"]),
            created_at=_aware(document["created_at"]),
            sources=list(sources) if sources is not None else None,
        )
