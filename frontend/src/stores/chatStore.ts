import { create } from "zustand";
import { createChat, deleteChat, listChats, loadLatestChat, streamChatMessage } from "../api/chats";
import { AccessBlockedError, ApiError, AuthRedirectError } from "../api/client";
import {
  applyStreamEvent,
  dropFailedMessages,
  failTurn,
  fromServerMessage,
  startTurn,
  type TurnMessage,
} from "../shared/chatTurn";
import { requestErrorLabel } from "../shared/labels";
import type { Chat } from "../types";

export const CHATS_PAGE_LIMIT = 50;

type ChatState = {
  chats: Chat[];
  chatsPhase: "idle" | "loading" | "ready" | "error";
  chatsError: string | null;
  totalChats: number;
  activeId: string | null;
  title: string;
  messages: TurnMessage[];
  messagesPhase: "idle" | "loading" | "ready" | "error";
  messagesError: string | null;
  totalMessages: number;
  sending: boolean;
  loadChats: () => Promise<void>;
  loadMoreChats: () => Promise<void>;
  openChat: (chatId: string) => Promise<void>;
  create: () => Promise<string>;
  remove: (chatId: string) => Promise<void>;
  send: (content: string) => Promise<void>;
  retry: (content: string) => Promise<void>;
  closeChat: () => void;
};

let streamAbort: AbortController | null = null;
let openSeq = 0;

function stopStream(): void {
  streamAbort?.abort();
  streamAbort = null;
}

function messageErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    return requestErrorLabel(error.status, error.code, "Не удалось отправить вопрос");
  }
  return "Ответ прервался и не был сохранён.";
}

export const useChatStore = create<ChatState>((set, get) => ({
  chats: [],
  chatsPhase: "idle",
  chatsError: null,
  totalChats: 0,
  activeId: null,
  title: "",
  messages: [],
  messagesPhase: "idle",
  messagesError: null,
  totalMessages: 0,
  sending: false,
  loadChats: async () => {
    const silent = get().chats.length > 0;
    if (!silent) set({ chatsPhase: "loading", chatsError: null });
    try {
      const page = await listChats(CHATS_PAGE_LIMIT, 0);
      set({
        chats: page.items,
        totalChats: page.total,
        chatsPhase: "ready",
        chatsError: null,
      });
    } catch (error) {
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      if (get().chats.length === 0) {
        set({ chatsPhase: "error", chatsError: "Не удалось загрузить чаты" });
      }
    }
  },
  loadMoreChats: async () => {
    if (get().chats.length >= get().totalChats) return;
    try {
      const page = await listChats(CHATS_PAGE_LIMIT, get().chats.length);
      set((state) => {
        const known = new Set(state.chats.map((chat) => chat.chat_id));
        return {
          chats: [...state.chats, ...page.items.filter((chat) => !known.has(chat.chat_id))],
          totalChats: page.total,
        };
      });
    } catch (error) {
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      set({ chatsError: "Не удалось загрузить остальные чаты" });
    }
  },
  openChat: async (chatId) => {
    stopStream();
    const seq = ++openSeq;
    set({
      activeId: chatId,
      messages: [],
      messagesPhase: "loading",
      messagesError: null,
      sending: false,
      title: get().chats.find((chat) => chat.chat_id === chatId)?.title ?? "",
    });
    try {
      const details = await loadLatestChat(chatId);
      if (seq !== openSeq || get().activeId !== chatId) return;
      set({
        title: details.title,
        messages: details.messages.map(fromServerMessage),
        totalMessages: details.total_messages,
        messagesPhase: "ready",
        messagesError: null,
      });
    } catch (error) {
      if (seq !== openSeq || get().activeId !== chatId) return;
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
      const text =
        error instanceof ApiError && (error.status === 404 || error.code === "chat_not_found")
          ? "Чат не найден"
          : "Не удалось загрузить сообщения";
      set({ messagesPhase: "error", messagesError: text, messages: [] });
    }
  },
  create: async () => {
    const chat = await createChat();
    set((state) => ({
      chats: [chat, ...state.chats.filter((item) => item.chat_id !== chat.chat_id)],
      totalChats: state.totalChats + (state.chats.some((item) => item.chat_id === chat.chat_id) ? 0 : 1),
      chatsPhase: "ready",
    }));
    return chat.chat_id;
  },
  remove: async (chatId) => {
    await deleteChat(chatId);
    if (get().activeId === chatId) stopStream();
    set((state) => ({
      chats: state.chats.filter((chat) => chat.chat_id !== chatId),
      totalChats: Math.max(0, state.totalChats - 1),
      activeId: state.activeId === chatId ? null : state.activeId,
      messages: state.activeId === chatId ? [] : state.messages,
      title: state.activeId === chatId ? "" : state.title,
      messagesPhase: state.activeId === chatId ? "idle" : state.messagesPhase,
    }));
  },
  send: async (raw) => {
    const content = raw.trim();
    const chatId = get().activeId;
    if (!chatId || get().sending) return;
    if (content.length < 1 || content.length > 4000) return;
    stopStream();
    const controller = new AbortController();
    streamAbort = controller;
    const tempUserId = `local-${crypto.randomUUID()}`;
    let turn = startTurn(get().messages, content, new Date().toISOString(), tempUserId);
    set({ messages: turn.messages, sending: true, messagesPhase: "ready", messagesError: null });
    try {
      const outcome = await streamChatMessage(
        chatId,
        content,
        (event) => {
          if (get().activeId !== chatId) return;
          turn = applyStreamEvent(turn, event, new Date().toISOString());
          set({ messages: turn.messages });
        },
        controller.signal,
      );
      if (controller.signal.aborted || get().activeId !== chatId) return;
      if (outcome === "error") {
        set({ sending: false });
        return;
      }
      try {
        const details = await loadLatestChat(chatId);
        if (get().activeId !== chatId) return;
        set({
          messages: details.messages.map(fromServerMessage),
          title: details.title,
          totalMessages: details.total_messages,
          sending: false,
        });
        set((state) => ({
          chats: state.chats.map((chat) =>
            chat.chat_id === chatId ? { ...chat, title: details.title, updated_at: details.updated_at } : chat,
          ),
        }));
      } catch {
        if (get().activeId === chatId) set({ messages: turn.messages, sending: false });
      }
      void get().loadChats();
    } catch (error) {
      if (controller.signal.aborted || get().activeId !== chatId) {
        set({ sending: false });
        return;
      }
      if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) {
        set({ sending: false });
        return;
      }
      turn = failTurn(turn, messageErrorText(error));
      set({ messages: turn.messages, sending: false });
    }
  },
  retry: async (content) => {
    set((state) => ({ messages: dropFailedMessages(state.messages) }));
    await get().send(content);
  },
  closeChat: () => {
    stopStream();
    openSeq += 1;
    set({
      activeId: null,
      messages: [],
      messagesPhase: "idle",
      messagesError: null,
      title: "",
      sending: false,
      totalMessages: 0,
    });
  },
}));

export function resetChatStore(): void {
  stopStream();
  openSeq += 1;
  useChatStore.setState(useChatStore.getInitialState(), true);
}
