import type { Source } from "../types";

export type SseEvent = {
  event: string;
  data: string;
};

export type ChatStreamEvent =
  | {
      type: "meta";
      chat_id: string;
      user_message_id: string;
      assistant_message_id: string;
      sources: Source[];
    }
  | { type: "delta"; content: string }
  | { type: "done"; finish_reason: string }
  | { type: "error"; code: string; message: string };

function normalizeNewlines(buffer: string): string {
  return buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

export function consumeSseBuffer(buffer: string): { events: SseEvent[]; rest: string } {
  const normalized = normalizeNewlines(buffer);
  const parts = normalized.split("\n\n");
  const rest = parts.pop() ?? "";
  const events: SseEvent[] = [];
  for (const part of parts) {
    const parsed = parseSseBlock(part);
    if (parsed) events.push(parsed);
  }
  return { events, rest };
}

export function flushSseBuffer(buffer: string): { events: SseEvent[]; rest: string } {
  if (!buffer.trim()) return { events: [], rest: "" };
  const normalized = normalizeNewlines(buffer);
  const terminated = normalized.endsWith("\n") ? `${normalized}\n` : `${normalized}\n\n`;
  return consumeSseBuffer(terminated);
}

function parseSseBlock(part: string): SseEvent | null {
  if (!part.trim()) return null;
  let event = "message";
  const dataLines: string[] = [];
  for (const line of part.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function readSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const source = asRecord(item);
    if (!source) {
      throw new Error("Invalid source");
    }
    return {
      file_id: requiredString(source, "file_id"),
      file_name: requiredString(source, "file_name"),
      page_number: requiredNumber(source, "page_number"),
      chunk_index: requiredNumber(source, "chunk_index"),
      snippet: typeof source.snippet === "string" ? source.snippet : "",
      score: typeof source.score === "number" ? source.score : 0,
    };
  });
}

function requiredString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Missing ${key}`);
  }
  return value;
}

function requiredNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Missing ${key}`);
  }
  return value;
}

export function parseChatStreamEvent(raw: SseEvent): ChatStreamEvent | null {
  if (raw.event !== "meta" && raw.event !== "delta" && raw.event !== "done" && raw.event !== "error") {
    return null;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(raw.data);
  } catch {
    throw new Error("Invalid SSE data");
  }
  const record = asRecord(payload);
  if (!record) throw new Error("Invalid SSE data");
  if (raw.event === "meta") {
    return {
      type: "meta",
      chat_id: requiredString(record, "chat_id"),
      user_message_id: requiredString(record, "user_message_id"),
      assistant_message_id: requiredString(record, "assistant_message_id"),
      sources: readSources(record.sources),
    };
  }
  if (raw.event === "delta") {
    return {
      type: "delta",
      content: typeof record.content === "string" ? record.content : "",
    };
  }
  if (raw.event === "done") {
    return {
      type: "done",
      finish_reason: typeof record.finish_reason === "string" ? record.finish_reason : "",
    };
  }
  return {
    type: "error",
    code: typeof record.code === "string" ? record.code : "",
    message: typeof record.message === "string" ? record.message : "",
  };
}

export function parseChatSseChunk(buffer: string): { events: ChatStreamEvent[]; rest: string } {
  const consumed = consumeSseBuffer(buffer);
  return {
    events: consumed.events.flatMap((event) => {
      const parsed = parseChatStreamEvent(event);
      return parsed ? [parsed] : [];
    }),
    rest: consumed.rest,
  };
}
