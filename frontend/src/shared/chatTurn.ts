import type { Message, Source } from "../types";
import { streamErrorLabel } from "./labels";
import type { ChatStreamEvent } from "./sse";

export type TurnMessage = {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  sources?: Source[];
  pending: boolean;
  saved: boolean;
  failed: boolean;
  errorText?: string;
  retryContent?: string;
};

export type LiveTurn = {
  messages: TurnMessage[];
  tempUserId: string;
  userMessageId: string | null;
  assistantMessageId: string | null;
  outcome: "open" | "saved" | "failed";
};

export function fromServerMessage(message: Message): TurnMessage {
  return {
    message_id: message.message_id,
    role: message.role,
    content: message.content,
    created_at: message.created_at,
    sources: message.role === "assistant" ? message.sources : undefined,
    pending: false,
    saved: true,
    failed: false,
  };
}

export function startTurn(existing: TurnMessage[], content: string, now: string, tempUserId: string): LiveTurn {
  return {
    messages: [
      ...existing,
      {
        message_id: tempUserId,
        role: "user",
        content,
        created_at: now,
        pending: true,
        saved: false,
        failed: false,
      },
    ],
    tempUserId,
    userMessageId: null,
    assistantMessageId: null,
    outcome: "open",
  };
}

export function applyStreamEvent(turn: LiveTurn, event: ChatStreamEvent, now: string): LiveTurn {
  if (turn.outcome !== "open") return turn;
  if (event.type === "meta") {
    if (turn.assistantMessageId) return turn;
    const userId = event.user_message_id;
    const messages = turn.messages.map((message) =>
      message.message_id === turn.tempUserId
        ? { ...message, message_id: userId, pending: false, saved: false, failed: false }
        : message,
    );
    return {
      ...turn,
      tempUserId: userId,
      userMessageId: userId,
      assistantMessageId: event.assistant_message_id,
      messages: [
        ...messages,
        {
          message_id: event.assistant_message_id,
          role: "assistant",
          content: "",
          created_at: now,
          sources: event.sources,
          pending: false,
          saved: false,
          failed: false,
        },
      ],
    };
  }
  if (event.type === "delta") {
    if (!turn.assistantMessageId) return turn;
    return {
      ...turn,
      messages: turn.messages.map((message) =>
        message.message_id === turn.assistantMessageId
          ? { ...message, content: message.content + event.content }
          : message,
      ),
    };
  }
  if (event.type === "done") {
    const ids = new Set([turn.userMessageId, turn.assistantMessageId, turn.tempUserId].filter((id) => id));
    return {
      ...turn,
      outcome: "saved",
      messages: turn.messages.map((message) =>
        ids.has(message.message_id)
          ? { ...message, pending: false, saved: true, failed: false, errorText: undefined }
          : message,
      ),
    };
  }
  return failTurn(turn, streamErrorLabel(event.code));
}

export function failTurn(turn: LiveTurn, errorText: string): LiveTurn {
  const ids = new Set(
    [turn.userMessageId, turn.assistantMessageId, turn.tempUserId].filter((id): id is string => Boolean(id)),
  );
  let lastId: string | null = null;
  for (const message of turn.messages) {
    if (ids.has(message.message_id)) lastId = message.message_id;
  }
  const question =
    turn.messages.find((message) => message.message_id === (turn.userMessageId ?? turn.tempUserId))?.content ?? "";
  return {
    ...turn,
    outcome: "failed",
    messages: turn.messages.map((message) => {
      if (!ids.has(message.message_id)) return message;
      const showsError = message.message_id === lastId;
      return {
        ...message,
        pending: false,
        saved: false,
        failed: true,
        errorText: showsError ? errorText : undefined,
        retryContent: showsError ? question : undefined,
      };
    }),
  };
}

export function dropFailedMessages(messages: TurnMessage[]): TurnMessage[] {
  return messages.filter((message) => !message.failed);
}
