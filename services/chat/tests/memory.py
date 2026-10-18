import uuid
from dataclasses import dataclass, field

from chat.repository import ChatRecord, FileRecord, MessageRecord, Turn
from chat.textutil import DEFAULT_TITLE
from chat.vectors import Hit


@dataclass
class StoredPoint:
    user_id: str
    document_id: str
    text: str
    page_number: int
    chunk_index: int
    score: float


class MemoryRepository:
    def __init__(self) -> None:
        self.chats: dict[str, ChatRecord] = {}
        self.messages: list[MessageRecord] = []
        self.files: list[FileRecord] = []
        self.calls: list[str] = []

    async def ensure_indexes(self) -> None:
        self.calls.append("ensure_indexes")

    async def create_chat(self, user_id: str, title: str, now) -> ChatRecord:
        self.calls.append("create_chat")
        chat = ChatRecord(
            chat_id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.chats[chat.chat_id] = chat
        return chat

    async def list_chats(self, user_id: str, limit: int, offset: int):
        self.calls.append("list_chats")
        items = [chat for chat in self.chats.values() if chat.user_id == user_id]
        items.sort(key=lambda chat: (chat.updated_at, chat.chat_id), reverse=True)
        return items[offset : offset + limit], len(items)

    async def get_chat(self, user_id: str, chat_id: str) -> ChatRecord | None:
        self.calls.append("get_chat")
        chat = self.chats.get(chat_id)
        if chat is None or chat.user_id != user_id:
            return None
        return chat

    async def delete_chat(self, user_id: str, chat_id: str) -> bool:
        self.calls.append("delete_chat")
        chat = self.chats.get(chat_id)
        if chat is None or chat.user_id != user_id:
            return False
        self.messages = [
            message
            for message in self.messages
            if not (message.chat_id == chat_id and message.user_id == user_id)
        ]
        del self.chats[chat_id]
        return True

    async def list_messages(self, user_id: str, chat_id: str, limit: int, offset: int):
        self.calls.append("list_messages")
        items = [
            message
            for message in self.messages
            if message.chat_id == chat_id and message.user_id == user_id
        ]
        items.sort(key=lambda message: (message.created_at, message.message_id))
        return items[offset : offset + limit], len(items)

    async def recent_messages(self, user_id: str, chat_id: str, limit: int) -> list[MessageRecord]:
        self.calls.append("recent_messages")
        items, _total = await self.list_messages(user_id, chat_id, limit=10_000, offset=0)
        if limit <= 0:
            return []
        return items[-limit:]

    async def ready_files(self, user_id: str, file_ids: list[str]) -> dict[str, FileRecord]:
        self.calls.append("ready_files")
        wanted = set(file_ids)
        found: dict[str, FileRecord] = {}
        for record in self.files:
            if record.file_id in wanted and record.user_id == user_id and record.status == "ready":
                found[record.file_id] = record
        return found

    async def save_turn(self, turn: Turn) -> None:
        self.calls.append("save_turn")
        self.messages.append(
            MessageRecord(
                message_id=turn.user_message_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                role="user",
                content=turn.question,
                created_at=turn.user_created_at,
                sources=None,
            )
        )
        self.messages.append(
            MessageRecord(
                message_id=turn.assistant_message_id,
                chat_id=turn.chat_id,
                user_id=turn.user_id,
                role="assistant",
                content=turn.answer,
                created_at=turn.assistant_created_at,
                sources=list(turn.sources),
            )
        )
        chat = self.chats[turn.chat_id]
        if chat.title == DEFAULT_TITLE:
            chat.title = turn.title
        chat.updated_at = turn.assistant_created_at

    async def close(self) -> None:
        self.calls.append("close")


@dataclass
class MemoryQdrant:
    points: list[StoredPoint] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)

    async def search(self, user_id: str, vector: list[float], limit: int) -> list[Hit]:
        self.calls.append({"user_id": user_id, "limit": limit, "dim": len(vector)})
        matched = [point for point in self.points if point.user_id == user_id]
        matched.sort(key=lambda point: point.score, reverse=True)
        return [
            Hit(
                document_id=point.document_id,
                user_id=point.user_id,
                text=point.text,
                page_number=point.page_number,
                chunk_index=point.chunk_index,
                score=point.score,
            )
            for point in matched[:limit]
        ]

    async def close(self) -> None:
        return None
