import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { Markdown } from "../components/Markdown";
import { SourceCard } from "../components/SourceCard";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/States";
import { RETRIEVAL_ONLY_NOTICE, requestErrorLabel } from "../shared/labels";
import type { TurnMessage } from "../shared/chatTurn";
import { useChatStore } from "../stores/chatStore";

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
    const view = chatId ? title || "Чат" : "Чат";
    document.title = `${view} · Документы · Filenkov`;
  }, [chatId, title]);

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
    <div className="view-in tool-split">
      <aside className="surface stack">
        <button type="button" className="btn is-block" onClick={() => void onCreate()}>
          Новый чат
        </button>
        {createError ? (
          <p className="banner error" role="alert">
            {createError}
          </p>
        ) : null}
        {chatsPhase === "loading" ? <LoadingBlock label="Загрузка чатов…" /> : null}
        {chatsPhase === "error" && chatsError ? (
          <ErrorBlock text={chatsError} onRetry={() => void loadChats()} />
        ) : null}
        {chatsPhase === "ready" && chats.length === 0 ? <p className="empty">Чатов пока нет.</p> : null}
        <ul className="choice-list choice-scroll">
          {chats.map((chat, index) => {
            const selected = chat.chat_id === chatId;
            return (
              <li key={chat.chat_id} className="choice">
                <button
                  type="button"
                  className="choice-main"
                  aria-current={selected ? "page" : undefined}
                  onClick={() => navigate(`/chat/${chat.chat_id}`)}
                >
                  <span className="choice-num">{String(index + 1).padStart(2, "0")}</span>
                  <span className="choice-body">
                    <span className="choice-title truncate">{chat.title}</span>
                  </span>
                  <span className="choice-arrow" aria-hidden="true">
                    →
                  </span>
                </button>
                {pendingDelete === chat.chat_id ? (
                  <div className="actions">
                    <button type="button" className="btn btn-ghost" onClick={() => setPendingDelete(null)}>
                      Отмена
                    </button>
                    <button type="button" className="btn btn-danger" onClick={() => void onDelete(chat.chat_id)}>
                      Удалить
                    </button>
                  </div>
                ) : (
                  <button type="button" className="quiet-action" onClick={() => setPendingDelete(chat.chat_id)}>
                    Удалить чат
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        {chats.length < totalChats ? (
          <button type="button" className="btn btn-ghost" onClick={() => void loadMoreChats()}>
            Ещё чаты
          </button>
        ) : null}
      </aside>

      <section className="surface thread-panel">
        {!chatId ? (
          <div className="page-pad">
            <p className="kicker">Документы</p>
            <h1>Чат</h1>
            <p className="muted page-lead">
              Выберите чат или создайте новый. История хранится на сервере и открывается после перезагрузки.
            </p>
          </div>
        ) : (
          <>
            <header className="thread-head">
              <div className="thread-measure">
                <p className="kicker">Документы</p>
                <h1 className="truncate">{title || "Чат"}</h1>
              </div>
            </header>
            <div ref={threadRef} className="thread">
              {messagesPhase === "loading" ? <LoadingBlock label="Загрузка сообщений…" /> : null}
              {messagesPhase === "error" && messagesError ? (
                <ErrorBlock text={messagesError} onRetry={() => void openChat(chatId)} />
              ) : null}
              {messagesPhase === "ready" && messages.length === 0 ? (
                <EmptyBlock title="Пустой чат" text="Задайте вопрос по загруженным документам." />
              ) : null}
              {totalMessages > messages.length && messages.length > 0 ? (
                <p className="meta">
                  Показаны последние {messages.length} из {totalMessages}.
                </p>
              ) : null}
              {messages.length > 0 ? (
                <div className="thread-measure">
                  {messages.map((message) => (
                    <MessageView
                      key={message.message_id}
                      message={message}
                      onRetry={(content) => void retry(content)}
                      retryDisabled={sending}
                    />
                  ))}
                </div>
              ) : null}
            </div>
            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <div className="composer-measure stack">
                <div className="field">
                  <label htmlFor="question">Вопрос</label>
                  <textarea
                    id="question"
                    placeholder="Спросите по документам"
                    value={draft}
                    maxLength={8000}
                    disabled={sending || activeId !== chatId}
                    aria-describedby="question-hint"
                    aria-invalid={tooLong || undefined}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        submit();
                      }
                    }}
                  />
                </div>
                <div className="actions">
                  <p id="question-hint" className={tooLong ? "meta is-danger" : "meta"}>
                    {tooLong
                      ? "Вопрос не длиннее 4000 символов."
                      : trimmed.length >= 3600
                        ? `${trimmed.length} / 4000`
                        : "Enter — отправить"}
                  </p>
                  <button type="submit" className="btn" disabled={sending || trimmed.length < 1 || tooLong}>
                    Спросить
                  </button>
                </div>
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
    <article>
      <div className={mine ? "a-callout" : undefined}>
        {mine ? (
          <p>{message.content}</p>
        ) : message.content ? (
          <Markdown text={message.content} />
        ) : !message.saved && !message.failed && !message.retrievalOnly ? (
          <p className="meta">…</p>
        ) : null}
        {message.retrievalOnly ? <p className="banner">{RETRIEVAL_ONLY_NOTICE}</p> : null}
        {message.pending ? <p className="meta">Отправляется…</p> : null}
        {sources.length > 0 ? (
          <ul className="source-list">
            {sources.map((source, index) => (
              <li key={`${source.file_id}-${source.page_number}-${source.chunk_index}-${index}`}>
                <SourceCard source={source} />
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {message.errorText ? (
        <div role="alert">
          <p className="banner error">{message.errorText}</p>
          <button
            type="button"
            className="btn"
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
