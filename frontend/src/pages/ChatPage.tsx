import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { Markdown } from "../components/Markdown";
import { SourceCard } from "../components/SourceCard";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/States";
import { RETRIEVAL_ONLY_NOTICE, requestErrorLabel } from "../shared/labels";
import { useChatStore } from "../stores/chatStore";
import type { TurnMessage } from "../shared/chatTurn";

export function ChatPage() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const chats = useChatStore((state) => state.chats);
  const chatsPhase = useChatStore((state) => state.chatsPhase);
  const chatsError = useChatStore((state) => state.chatsError);
  const totalChats = useChatStore((state) => state.totalChats);
  const title = useChatStore((state) => state.title);
  const messages = useChatStore((state) => state.messages);
  const messagesPhase = useChatStore((state) => state.messagesPhase);
  const messagesError = useChatStore((state) => state.messagesError);
  const totalMessages = useChatStore((state) => state.totalMessages);
  const sending = useChatStore((state) => state.sending);
  const activeId = useChatStore((state) => state.activeId);
  const loadChats = useChatStore((state) => state.loadChats);
  const loadMoreChats = useChatStore((state) => state.loadMoreChats);
  const openChat = useChatStore((state) => state.openChat);
  const closeChat = useChatStore((state) => state.closeChat);
  const create = useChatStore((state) => state.create);
  const remove = useChatStore((state) => state.remove);
  const send = useChatStore((state) => state.send);
  const retry = useChatStore((state) => state.retry);
  const [draft, setDraft] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadChats();
  }, [loadChats]);

  useEffect(() => {
    setDraft("");
  }, [chatId]);

  useEffect(() => {
    if (!chatId) {
      closeChat();
      return;
    }
    void openChat(chatId);
  }, [chatId, openChat, closeChat]);

  useEffect(() => {
    return () => closeChat();
  }, [closeChat]);

  useEffect(() => {
    const node = threadRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [messages, sending]);

  const trimmed = draft.trim();
  const tooLong = trimmed.length > 4000;

  async function onCreate() {
    setCreateError(null);
    try {
      const id = await create();
      navigate(`/chat/${id}`);
    } catch (error) {
      if (error instanceof ApiError) {
        setCreateError(requestErrorLabel(error.status, error.code, "Не удалось создать чат"));
      } else {
        setCreateError("Не удалось создать чат");
      }
    }
  }

  async function onDelete(id: string) {
    try {
      await remove(id);
      setPendingDelete(null);
      if (chatId === id) navigate("/chat");
    } catch (error) {
      if (error instanceof ApiError) {
        setCreateError(requestErrorLabel(error.status, error.code, "Не удалось удалить чат"));
      } else {
        setCreateError("Не удалось удалить чат");
      }
    }
  }

  function submit() {
    if (!chatId || sending || trimmed.length < 1 || tooLong) return;
    const text = trimmed;
    setDraft("");
    void send(text);
  }

  return (
    <div className="grid gap-4 md:grid-cols-[17rem_minmax(0,1fr)] md:items-start">
      <aside className="rounded-2xl border border-line bg-sheet p-3">
        <button
          type="button"
          className="w-full rounded-full bg-pine px-3 py-2 text-sm text-sheet"
          onClick={() => void onCreate()}
        >
          Новый чат
        </button>
        {createError ? <p className="mt-2 text-sm text-red-900">{createError}</p> : null}
        <div className="mt-3">
          {chatsPhase === "loading" ? <LoadingBlock label="Загрузка чатов…" /> : null}
          {chatsPhase === "error" && chatsError ? <ErrorBlock text={chatsError} onRetry={() => void loadChats()} /> : null}
          {chatsPhase === "ready" && chats.length === 0 ? (
            <p className="px-1 py-3 text-sm text-muted">Чатов пока нет.</p>
          ) : null}
          <ul className="mt-1 max-h-[28rem] space-y-1 overflow-auto">
            {chats.map((chat) => {
              const selected = chat.chat_id === chatId;
              return (
                <li key={chat.chat_id} className={`rounded-xl px-2 py-2 ${selected ? "bg-paper" : ""}`}>
                  <button
                    type="button"
                    className="w-full truncate text-left text-sm"
                    onClick={() => navigate(`/chat/${chat.chat_id}`)}
                  >
                    {chat.title}
                  </button>
                  {pendingDelete === chat.chat_id ? (
                    <div className="mt-1 flex gap-2 text-xs">
                      <button type="button" className="text-red-900" onClick={() => void onDelete(chat.chat_id)}>
                        Удалить
                      </button>
                      <button type="button" onClick={() => setPendingDelete(null)}>
                        Отмена
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="mt-1 text-xs text-muted"
                      onClick={() => setPendingDelete(chat.chat_id)}
                    >
                      Удалить чат
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {chats.length < totalChats ? (
            <button type="button" className="mt-2 text-sm text-pine" onClick={() => void loadMoreChats()}>
              Ещё чаты
            </button>
          ) : null}
        </div>
      </aside>

      <section className="flex min-h-[32rem] flex-col rounded-2xl border border-line bg-sheet">
        {!chatId ? (
          <div className="p-4">
            <EmptyBlock title="Чат" text="Выберите чат или создайте новый. История хранится на сервере и открывается после перезагрузки." />
          </div>
        ) : (
          <>
            <header className="border-b border-line px-4 py-3">
              <h1 className="serif truncate text-2xl">{title || "Чат"}</h1>
            </header>
            <div ref={threadRef} className="flex-1 space-y-4 overflow-auto px-4 py-4">
              {messagesPhase === "loading" ? <LoadingBlock label="Загрузка сообщений…" /> : null}
              {messagesPhase === "error" && messagesError ? (
                <ErrorBlock text={messagesError} onRetry={() => void openChat(chatId)} />
              ) : null}
              {messagesPhase === "ready" && messages.length === 0 ? (
                <EmptyBlock title="Пустой чат" text="Задайте вопрос по загруженным документам." />
              ) : null}
              {totalMessages > messages.length && messages.length > 0 ? (
                <p className="text-center text-xs text-muted">Показаны последние {messages.length} из {totalMessages}.</p>
              ) : null}
              {messages.map((message) => (
                <MessageView
                  key={message.message_id}
                  message={message}
                  onRetry={(content) => void retry(content)}
                  retryDisabled={sending}
                />
              ))}
            </div>
            <form
              className="border-t border-line p-3"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <label className="sr-only" htmlFor="question">
                Вопрос
              </label>
              <textarea
                id="question"
                className="min-h-24 w-full resize-y rounded-xl border border-line bg-paper px-3 py-2"
                placeholder="Спросите по документам"
                value={draft}
                maxLength={8000}
                disabled={sending || activeId !== chatId}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <p className={`text-xs ${tooLong ? "text-red-800" : "text-muted"}`}>
                  {tooLong ? "Вопрос не длиннее 4000 символов." : trimmed.length >= 3600 ? `${trimmed.length} / 4000` : "Enter — отправить"}
                </p>
                <button
                  type="submit"
                  className="rounded-full bg-pine px-4 py-2 text-sm text-sheet disabled:opacity-40"
                  disabled={sending || trimmed.length < 1 || tooLong}
                >
                  Спросить
                </button>
              </div>
            </form>
          </>
        )}
      </section>
    </div>
  );
}

function MessageView({
  message,
  onRetry,
  retryDisabled,
}: {
  message: TurnMessage;
  onRetry: (content: string) => void;
  retryDisabled: boolean;
}) {
  const mine = message.role === "user";
  const sources = message.role === "assistant" ? (message.sources ?? []) : [];
  return (
    <article className={`flex max-w-[42rem] flex-col ${mine ? "ml-auto items-end" : "items-start"}`}>
      <div className={mine ? "rounded-2xl bg-pine px-3 py-2 text-sheet" : "w-full"}>
        {mine ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : message.content ? (
          <Markdown text={message.content} />
        ) : !message.saved && !message.failed && !message.retrievalOnly ? (
          <p className="text-muted">…</p>
        ) : null}
        {message.retrievalOnly ? <p>{RETRIEVAL_ONLY_NOTICE}</p> : null}
        {message.pending ? <p className="mt-1 text-xs text-sheet/80">Отправляется…</p> : null}
        {sources.length > 0 ? (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {sources.map((source, index) => (
              <li key={`${source.file_id}-${source.page_number}-${source.chunk_index}-${index}`}>
                <SourceCard source={source} />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {message.errorText ? (
        <div className="mt-2 text-sm text-red-900" role="alert">
          <p>{message.errorText}</p>
          <button
            type="button"
            className="mt-1 underline disabled:opacity-40"
            disabled={retryDisabled}
            onClick={() => onRetry(message.retryContent ?? message.content)}
          >
            Повторить
          </button>
        </div>
      ) : null}
    </article>
  );
}
