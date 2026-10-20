import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from chat.config import Settings
from chat.errors import ChatNotFound, DependencyUnavailable, UpstreamFailed, UpstreamTimeout
from chat.llm import ProviderUnavailable
from chat.prompt import PromptSource, build_llm_messages
from chat.repository import ChatRecord, ChatRepository, FileRecord, MessageRecord, Turn
from chat.sse import sse
from chat.textutil import NOT_FOUND, format_dt, snippet, title_from_question
from chat.vectors import Hit, VectorSearch

logger = logging.getLogger("chat")


@dataclass(slots=True)
class Source:
    file_id: str
    file_name: str
    page_number: int
    chunk_index: int
    text: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "snippet": snippet(self.text),
            "score": self.score,
        }


@dataclass(slots=True)
class AnswerSession:
    chat_id: str
    user_id: str
    content: str
    user_message_id: str
    assistant_message_id: str
    sources: list[Source]
    request_id: str
    handle: object | None = None
    primed: list[str] = field(default_factory=list)
    retrieval_only: bool = False


class ChatService:
    def __init__(
        self,
        settings: Settings,
        repo: ChatRepository,
        vectors: VectorSearch,
        embedder: object,
        llm: object,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._vectors = vectors
        self._embedder = embedder
        self._llm = llm
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def create_chat(self, user_id: str, title: str) -> ChatRecord:
        return await self._repo.create_chat(user_id, title, self._now())

    async def list_chats(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[ChatRecord], int]:
        return await self._repo.list_chats(user_id, limit, offset)

    async def get_chat(self, user_id: str, chat_id: str) -> ChatRecord:
        chat = await self._repo.get_chat(user_id, chat_id)
        if chat is None:
            raise ChatNotFound()
        return chat

    async def list_messages(
        self, user_id: str, chat_id: str, limit: int, offset: int
    ) -> tuple[ChatRecord, list[MessageRecord], int]:
        chat = await self.get_chat(user_id, chat_id)
        messages, total = await self._repo.list_messages(user_id, chat_id, limit, offset)
        return chat, messages, total

    async def delete_chat(self, user_id: str, chat_id: str) -> None:
        deleted = await self._repo.delete_chat(user_id, chat_id)
        if not deleted:
            raise ChatNotFound()

    async def open_answer(
        self, *, user_id: str, chat_id: str, content: str, request_id: str
    ) -> AnswerSession:
        chat = await self._repo.get_chat(user_id, chat_id)
        if chat is None:
            raise ChatNotFound()
        user_message_id = str(uuid.uuid4())
        assistant_message_id = str(uuid.uuid4())
        log_extra = {
            "request_id": request_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": user_message_id,
        }
        vector = await self._embedder.embed_query(content, request_id)
        hits = await self._vectors.search(user_id, vector, self._settings.rag_top_k)
        file_ids = [hit.document_id for hit in hits if hit.document_id]
        files = await self._repo.ready_files(user_id, file_ids) if file_ids else {}
        sources = select_sources(hits, files, user_id, self._settings.rag_min_score)
        logger.info("retrieved %s sources", len(sources), extra=log_extra)
        session = AnswerSession(
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            sources=sources,
            request_id=request_id,
        )
        if not sources:
            return session
        history: list[MessageRecord] = []
        if self._settings.rag_context_messages > 0:
            history = await self._repo.recent_messages(
                user_id, chat_id, self._settings.rag_context_messages
            )
        messages = build_llm_messages(history, content, [_prompt_source(item) for item in sources])
        handle = _LLMHandle(self._llm.stream(messages, request_id))
        try:
            try:
                first = await anext(handle)
            except StopAsyncIteration:
                first = None
        except ProviderUnavailable:
            await handle.aclose()
            if session.sources:
                session.retrieval_only = True
                logger.info("answer fell back to retrieval_only", extra=log_extra)
                return session
            raise
        except BaseException:
            await handle.aclose()
            raise
        session.handle = handle
        session.primed = [first] if first else []
        return session

    async def iter_sse(self, session: AnswerSession) -> AsyncIterator[bytes]:
        """Stream meta, deltas, and done.

        A client disconnect cancels this generator before `done`. The turn is
        written only after the answer is complete, so the cancel skips persistence.
        """
        parts: list[str] = []
        handle = session.handle if isinstance(session.handle, _LLMHandle) else None
        try:
            payloads = [source.as_dict() for source in session.sources]
            yield sse(
                "meta",
                {
                    "chat_id": session.chat_id,
                    "user_message_id": session.user_message_id,
                    "assistant_message_id": session.assistant_message_id,
                    "sources": payloads,
                },
            )
            stored_reason: str | None = None
            if session.retrieval_only:
                stored_reason = "retrieval_only"
            elif handle is None:
                parts.append(NOT_FOUND)
                yield sse("delta", {"content": NOT_FOUND})
            else:
                for token in session.primed:
                    parts.append(token)
                    yield sse("delta", {"content": token})
                async for token in handle:
                    parts.append(token)
                    yield sse("delta", {"content": token})
            now = self._now()
            await self._repo.save_turn(
                Turn(
                    chat_id=session.chat_id,
                    user_id=session.user_id,
                    user_message_id=session.user_message_id,
                    assistant_message_id=session.assistant_message_id,
                    question=session.content,
                    answer="".join(parts),
                    sources=payloads,
                    user_created_at=now,
                    assistant_created_at=now + timedelta(milliseconds=1),
                    title=title_from_question(session.content),
                    finish_reason=stored_reason,
                )
            )
            yield sse("done", {"finish_reason": stored_reason or "stop"})
        except UpstreamTimeout:
            logger.warning(
                "llm timed out",
                extra={
                    "request_id": session.request_id,
                    "user_id": session.user_id,
                    "chat_id": session.chat_id,
                    "message_id": session.user_message_id,
                },
            )
            yield sse("error", {"code": "upstream_timeout", "message": "LLM timed out"})
        except (UpstreamFailed, DependencyUnavailable) as exc:
            logger.warning(
                "answer failed: %s",
                exc.code,
                extra={
                    "request_id": session.request_id,
                    "user_id": session.user_id,
                    "chat_id": session.chat_id,
                    "message_id": session.user_message_id,
                },
            )
            yield sse("error", {"code": exc.code, "message": exc.message})
        finally:
            if handle is not None:
                await handle.aclose()


class _LLMHandle:
    def __init__(self, agen: AsyncIterator[str]) -> None:
        self._agen = agen
        self._closed = False

    def __aiter__(self) -> "_LLMHandle":
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await anext(self._agen)
        except StopAsyncIteration:
            self._closed = True
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        aclose = getattr(self._agen, "aclose", None)
        if aclose is not None:
            await aclose()


def select_sources(
    hits: list[Hit],
    files: dict[str, FileRecord],
    user_id: str,
    min_score: float,
) -> list[Source]:
    chosen: list[Source] = []
    for hit in hits:
        if hit.user_id and hit.user_id != user_id:
            continue
        record = files.get(hit.document_id)
        if record is None or record.user_id != user_id or record.status != "ready":
            continue
        if min_score > 0 and hit.score < min_score:
            continue
        if hit.page_number < 1 or hit.chunk_index < 0:
            continue
        chosen.append(
            Source(
                file_id=record.file_id,
                file_name=record.file_name,
                page_number=hit.page_number,
                chunk_index=hit.chunk_index,
                text=hit.text,
                score=hit.score,
            )
        )
    chosen.sort(key=lambda source: source.score, reverse=True)
    return chosen


def _prompt_source(source: Source) -> PromptSource:
    return PromptSource(source.file_name, source.page_number, source.text)


def chat_payload(chat: ChatRecord) -> dict[str, object]:
    return {
        "chat_id": chat.chat_id,
        "title": chat.title,
        "created_at": format_dt(chat.created_at),
        "updated_at": format_dt(chat.updated_at),
    }


def message_payload(message: MessageRecord) -> dict[str, object]:
    body: dict[str, object] = {
        "message_id": message.message_id,
        "role": message.role,
        "content": message.content,
        "created_at": format_dt(message.created_at),
    }
    if message.role == "assistant":
        body["sources"] = message.sources or []
    if message.finish_reason is not None:
        body["finish_reason"] = message.finish_reason
    return body
