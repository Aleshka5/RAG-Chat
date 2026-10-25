import type { Chat, ChatDetails, ChatList, SearchMode } from "../types";
import { apiFetch, apiJson, responseError, StreamBrokenError } from "./client";
import { consumeSseBuffer, flushSseBuffer, parseChatStreamEvent, type ChatStreamEvent } from "../shared/sse";

export function listChats(limit: number, offset: number): Promise<ChatList> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiJson<ChatList>(`/api/chats?${params.toString()}`);
}

export function createChat(): Promise<Chat> {
  return apiJson<Chat>("/api/chats", { method: "POST" });
}

export function getChat(chatId: string, limit: number, offset: number, signal?: AbortSignal): Promise<ChatDetails> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiJson<ChatDetails>(`/api/chats/${encodeURIComponent(chatId)}?${params.toString()}`, { signal });
}

export const MESSAGE_PAGE_LIMIT = 200;

export async function loadLatestChat(chatId: string, signal?: AbortSignal): Promise<ChatDetails> {
  const first = await getChat(chatId, MESSAGE_PAGE_LIMIT, 0, signal);
  if (first.total_messages <= first.messages.length) return first;
  const offset = Math.max(0, first.total_messages - MESSAGE_PAGE_LIMIT);
  return getChat(chatId, MESSAGE_PAGE_LIMIT, offset, signal);
}

export function deleteChat(chatId: string): Promise<void> {
  return apiJson<void>(`/api/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" });
}

async function readEventStream(
  response: Response,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<"done" | "error"> {
  if (!response.body) throw new StreamBrokenError();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let outcome: "done" | "error" | null = null;

  const take = (next: string, flush: boolean) => {
    const consumed = flush ? flushSseBuffer(next) : consumeSseBuffer(next);
    buffer = consumed.rest;
    for (const raw of consumed.events) {
      const event = parseChatStreamEvent(raw);
      if (!event) continue;
      onEvent(event);
      if (event.type === "done") outcome = "done";
      if (event.type === "error") outcome = "error";
    }
  };

  while (!outcome) {
    const { done, value } = await reader.read();
    if (done) break;
    take(buffer + decoder.decode(value, { stream: true }), false);
  }
  if (!outcome) take(buffer + decoder.decode(), true);
  if (!outcome) throw new StreamBrokenError();
  return outcome;
}

export async function streamChatMessage(
  chatId: string,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
  mode?: SearchMode,
): Promise<"done" | "error"> {
  const payload = mode === "images" ? { content, mode: "images" as const } : { content };
  const response = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
    method: "POST",
    signal,
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await responseError(response);
  return readEventStream(response, onEvent);
}
