import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { ImageHitList } from "../components/ImageHit";
import { Markdown } from "../components/Markdown";
import { SourceCard } from "../components/SourceCard";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/States";
import { RETRIEVAL_ONLY_NOTICE, requestErrorLabel } from "../shared/labels";
import type { TurnMessage } from "../shared/chatTurn";
import { useChatStore } from "../stores/chatStore";
import type { SearchMode } from "../types";

function mediaMatches(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(query).matches;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => mediaMatches(query));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

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
  const [mode, setMode] = useState<SearchMode>("documents");
  const [createError, setCreateError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [armedId, setArmedId] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const compact = useMediaQuery("(max-width: 759px)");
  const coarse = useMediaQuery("(pointer: coarse)");

  useEffect(() => {
    const view = chatId ? title || "Chat" : "Chat";
    document.title = `${view} · Documents · Filenkov`;
  }, [chatId, title]);

  useEffect(() => {
    void loadChats();
  }, [loadChats]);

  useEffect(() => {
    setDraft("");
    setMode("documents");
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

  useEffect(() => {
    if (!historyOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setHistoryOpen(false);
      setArmedId(null);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  useEffect(() => {
    if (!pendingDelete) return;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || deleting) return;
      event.stopImmediatePropagation();
      setPendingDelete(null);
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [pendingDelete, deleting]);

  const trimmed = draft.trim();
  const tooLong = trimmed.length > 4000;

  function closeHistory() {
    setHistoryOpen(false);
    setArmedId(null);
  }

  function openListedChat(id: string) {
    closeHistory();
    navigate(`/chat/${id}`);
  }

  async function onCreate() {
    setCreateError(null);
    try {
      const id = await create();
      closeHistory();
      navigate(`/chat/${id}`);
    } catch (error) {
      if (error instanceof ApiError) {
        setCreateError(requestErrorLabel(error.status, error.code, "Could not create chat"));
      } else {
        setCreateError("Could not create chat");
      }
    }
  }

  async function onDelete(id: string) {
    setDeleting(true);
    try {
      await remove(id);
      setPendingDelete(null);
      if (chatId === id) {
        closeHistory();
        navigate("/chat");
      }
    } catch (error) {
      if (error instanceof ApiError) {
        setCreateError(requestErrorLabel(error.status, error.code, "Could not delete chat"));
      } else {
        setCreateError("Could not delete chat");
      }
    } finally {
      setDeleting(false);
    }
  }

  function submit() {
    if (!chatId || sending || trimmed.length < 1 || tooLong) return;
    const text = trimmed;
    setDraft("");
    void send(text, mode);
  }

  const historyHidden = compact && !historyOpen;
  const pendingChat = chats.find((chat) => chat.chat_id === pendingDelete) ?? null;

  const history = (
    <>
      {historyOpen ? (
        <button type="button" className="chat-history-scrim" aria-label="Close" onClick={closeHistory} />
      ) : null}
      <aside
        id="chat-history"
        className={`surface stack chat-history${historyOpen ? " is-open" : ""}`}
        aria-label="Chats"
        aria-hidden={historyHidden ? true : undefined}
        inert={historyHidden ? true : undefined}
      >
        <div className="chat-history-tools">
          <button type="button" className="btn btn-ghost" onClick={closeHistory}>
            Close
          </button>
        </div>
        <button type="button" className="btn is-block" onClick={() => void onCreate()}>
          New chat
        </button>
        {createError ? (
          <p className="banner error" role="alert">
            {createError}
          </p>
        ) : null}
        {chatsPhase === "loading" ? <LoadingBlock label="Loading chats…" /> : null}
        {chatsPhase === "error" && chatsError ? (
          <ErrorBlock text={chatsError} onRetry={() => void loadChats()} />
        ) : null}
        {chatsPhase === "ready" && chats.length === 0 ? <p className="empty">No chats yet.</p> : null}
        <ul className="choice-list choice-scroll">
          {chats.map((chat, index) => {
            const selected = chat.chat_id === chatId;
            const armed = coarse && armedId === chat.chat_id;
            return (
              <li key={chat.chat_id} className={`choice chat-row${armed ? " is-armed" : ""}`}>
                <button
                  type="button"
                  className="choice-main"
                  aria-current={selected ? "page" : undefined}
                  onClick={() => {
                    if (coarse && armedId !== chat.chat_id) {
                      setArmedId(chat.chat_id);
                      return;
                    }
                    openListedChat(chat.chat_id);
                  }}
                >
                  <span className="choice-num">{String(index + 1).padStart(2, "0")}</span>
                  <span className="choice-body">
                    <span className="choice-title truncate">{chat.title}</span>
                  </span>
                  <span className="choice-arrow" aria-hidden="true">
                    →
                  </span>
                </button>
                {pendingDelete === chat.chat_id ? null : (
                  <button type="button" className="chat-row-delete" onClick={() => setPendingDelete(chat.chat_id)}>
                    Delete chat
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        {chats.length < totalChats ? (
          <button type="button" className="btn btn-ghost" onClick={() => void loadMoreChats()}>
            Load more
          </button>
        ) : null}
      </aside>
    </>
  );

  return (
    <div className="view-in chat-layout">
      <button
        type="button"
        className="btn chat-history-open"
        aria-expanded={historyOpen}
        aria-controls="chat-history"
        onClick={() => setHistoryOpen(true)}
      >
        Chats
      </button>
      {compact ? createPortal(history, document.body) : history}

      <section className="surface thread-panel">
        {!chatId ? (
          <div className="page-pad">
            <p className="kicker">Documents</p>
            <h1>Chat</h1>
            <p className="muted page-lead">
              Choose a chat or start a new one. History is stored on the server and opens after a reload.
            </p>
          </div>
        ) : (
          <>
            <header className="thread-head">
              <div className="thread-measure">
                <p className="kicker">Documents</p>
                <h1 className="truncate">{title || "Chat"}</h1>
              </div>
            </header>
            <div ref={threadRef} className="thread">
              {messagesPhase === "loading" ? <LoadingBlock label="Loading messages…" /> : null}
              {messagesPhase === "error" && messagesError ? (
                <ErrorBlock text={messagesError} onRetry={() => void openChat(chatId)} />
              ) : null}
              {messagesPhase === "ready" && messages.length === 0 ? (
                <EmptyBlock title="Empty chat" text="Ask a question about the uploaded documents." />
              ) : null}
              {totalMessages > messages.length && messages.length > 0 ? (
                <p className="meta">
                  Showing the latest {messages.length} of {totalMessages}.
                </p>
              ) : null}
              {messages.length > 0 ? (
                <div className="thread-measure">
                  {messages.map((message) => (
                    <MessageView
                      key={message.message_id}
                      message={message}
                      onRetry={(content, retryMode) => void retry(content, retryMode)}
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
                <div className="mode-switch" role="group" aria-label="Search mode">
                  <button
                    type="button"
                    className={mode === "documents" ? "btn btn-small" : "btn btn-small btn-ghost"}
                    aria-pressed={mode === "documents"}
                    disabled={sending || activeId !== chatId}
                    onClick={() => setMode("documents")}
                  >
                    Documents
                  </button>
                  <button
                    type="button"
                    className={mode === "images" ? "btn btn-small" : "btn btn-small btn-ghost"}
                    aria-pressed={mode === "images"}
                    disabled={sending || activeId !== chatId}
                    onClick={() => setMode("images")}
                  >
                    Images
                  </button>
                </div>
                <div className="field">
                  <label htmlFor="question">Question</label>
                  <textarea
                    id="question"
                    placeholder={mode === "images" ? "Search images" : "Ask about the documents"}
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
                      ? "Question must be 4000 characters or fewer."
                      : trimmed.length >= 3600
                        ? `${trimmed.length} / 4000`
                        : "Enter to send"}
                  </p>
                  <button type="submit" className="btn" disabled={sending || trimmed.length < 1 || tooLong}>
                    Ask
                  </button>
                </div>
              </div>
            </form>
          </>
        )}
      </section>
      {pendingChat
        ? createPortal(
            <DeleteChatDialog
              title={pendingChat.title}
              busy={deleting}
              onCancel={() => setPendingDelete(null)}
              onConfirm={() => void onDelete(pendingChat.chat_id)}
            />,
            document.body,
          )
        : null}
    </div>
  );
}

function DeleteChatDialog({
  title,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="delete-chat-title">
      <button type="button" className="overlay-dismiss" aria-label="Close" onClick={onCancel} disabled={busy} />
      <div className="panel">
        <h2 id="delete-chat-title" ref={titleRef} tabIndex={-1}>
          Delete chat?
        </h2>
        <div className="stack">
          <p>{title} will be permanently deleted.</p>
          <div className="actions">
            <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageView({
  message,
  onRetry,
  retryDisabled,
}: {
  message: TurnMessage;
  onRetry: (content: string, mode?: SearchMode) => void;
  retryDisabled: boolean;
}) {
  const mine = message.role === "user";
  const sources = message.role === "assistant" ? (message.sources ?? []) : [];
  const images = message.role === "assistant" && Array.isArray(message.images) ? message.images : [];
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
        {message.pending ? <p className="meta">Sending…</p> : null}
        {sources.length > 0 ? (
          <ul className="source-list">
            {sources.map((source, index) => (
              <li key={`${source.file_id}-${source.page_number}-${source.chunk_index}-${index}`}>
                <SourceCard source={source} />
              </li>
            ))}
          </ul>
        ) : null}
        {images.length > 0 ? <ImageHitList images={images} /> : null}
      </div>
      {message.errorText ? (
        <div role="alert">
          <p className="banner error">{message.errorText}</p>
          <button
            type="button"
            className="btn"
            disabled={retryDisabled}
            onClick={() => onRetry(message.retryContent ?? message.content, message.retryMode)}
          >
            Retry
          </button>
        </div>
      ) : null}
    </article>
  );
}
