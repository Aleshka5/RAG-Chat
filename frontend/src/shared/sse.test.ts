import { describe, expect, it } from "vitest";
import { consumeSseBuffer, flushSseBuffer, parseChatSseChunk, parseChatStreamEvent } from "./sse";

const SAMPLE = [
  "event: meta",
  'data: {"chat_id":"b7e1a2c4-1111-4222-8333-444455556666","user_message_id":"11111111-1111-4111-8111-111111111111","assistant_message_id":"22222222-2222-4222-8222-222222222222","sources":[{"file_id":"6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f","file_name":"Отчёт.pdf","page_number":5,"chunk_index":3,"snippet":"Срок годности","score":0.81}]}',
  "",
  "id: 15",
  "event: delta",
  'data: {"content":"Срок"}',
  "",
  "event: delta",
  'data: {"content":" годности"}',
  "",
  "event: done",
  'data: {"finish_reason":"stop"}',
  "",
].join("\n") + "\n";

function feed(chunks: string[]) {
  let buffer = "";
  const events = [];
  for (const chunk of chunks) {
    buffer += chunk;
    const parsed = parseChatSseChunk(buffer);
    buffer = parsed.rest;
    events.push(...parsed.events);
  }
  if (buffer.trim()) {
    const flushed = flushSseBuffer(buffer);
    events.push(
      ...flushed.events.flatMap((raw) => {
        const event = parseChatStreamEvent(raw);
        return event ? [event] : [];
      }),
    );
  }
  return events;
}

describe("SSE chat stream", () => {
  it("parses meta, delta and done in order and ignores id", () => {
    const events = feed([SAMPLE]);
    expect(events.map((event) => event.type)).toEqual(["meta", "delta", "delta", "done"]);
    expect(events[0]).toMatchObject({
      type: "meta",
      user_message_id: "11111111-1111-4111-8111-111111111111",
      assistant_message_id: "22222222-2222-4222-8222-222222222222",
      sources: [
        {
          file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
          file_name: "Отчёт.pdf",
          page_number: 5,
        },
      ],
    });
    expect(events[1]).toEqual({ type: "delta", content: "Срок" });
    expect(events[2]).toEqual({ type: "delta", content: " годности" });
    expect(events[3]).toEqual({ type: "done", finish_reason: "stop" });
  });

  it("keeps a partial event in the buffer until the blank line arrives", () => {
    const splitAt = SAMPLE.indexOf('data: {"content":"Срок"}') + 8;
    const first = parseChatSseChunk(SAMPLE.slice(0, splitAt));
    expect(first.events.map((event) => event.type)).toEqual(["meta"]);
    expect(first.rest.length).toBeGreaterThan(0);
    const second = parseChatSseChunk(first.rest + SAMPLE.slice(splitAt));
    expect(second.events.map((event) => event.type)).toEqual(["delta", "delta", "done"]);
  });

  it("reassembles a stream that is cut on every character", () => {
    const events = feed(SAMPLE.split(""));
    expect(events.map((event) => event.type)).toEqual(["meta", "delta", "delta", "done"]);
    const text = events
      .filter((event) => event.type === "delta")
      .map((event) => (event.type === "delta" ? event.content : ""))
      .join("");
    expect(text).toBe("Срок годности");
  });

  it("parses an error event and does not require done", () => {
    const raw = ["event: error", 'data: {"code":"upstream_timeout","message":"LLM timed out"}', ""].join("\n") + "\n";
    const { events } = parseChatSseChunk(raw);
    expect(events).toEqual([{ type: "error", code: "upstream_timeout", message: "LLM timed out" }]);
  });

  it("joins continued data lines and accepts CRLF", () => {
    const raw = "event: delta\r\ndata: {\"content\":\r\ndata: \"А\"}\r\n\r\n";
    const { events, rest } = parseChatSseChunk(raw);
    expect(rest).toBe("");
    expect(events).toEqual([{ type: "delta", content: "А" }]);
  });

  it("copies a non-empty unit label and omits an empty one", () => {
    const office = {
      file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
      file_name: "Отчёт.docx",
      page_number: 1,
      chunk_index: 0,
      snippet: "текст",
      score: 0.9,
      unit_label: "Введение",
    };
    const pdf = {
      file_id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
      file_name: "Отчёт.pdf",
      page_number: 4,
      chunk_index: 1,
      snippet: "страница",
      score: 0.4,
      unit_label: "",
    };
    const raw =
      [
        "event: meta",
        `data: ${JSON.stringify({
          chat_id: "b7e1a2c4-1111-4222-8333-444455556666",
          user_message_id: "11111111-1111-4111-8111-111111111111",
          assistant_message_id: "22222222-2222-4222-8222-222222222222",
          sources: [office, pdf],
        })}`,
        "",
        "",
      ].join("\n");
    const { events } = parseChatSseChunk(raw);
    expect(events[0]).toMatchObject({
      type: "meta",
      sources: [
        { file_name: "Отчёт.docx", page_number: 1, unit_label: "Введение" },
        { file_name: "Отчёт.pdf", page_number: 4 },
      ],
    });
    expect(events[0]?.type === "meta" && events[0].sources[1].unit_label).toBeUndefined();
  });

  it("reads image hits beside an empty source list", () => {
    const image = {
      file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
      file_name: "a.jpg",
      score: 0.77,
      content_path: "/api/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/content",
    };
    const raw =
      [
        "event: meta",
        `data: ${JSON.stringify({
          chat_id: "b7e1a2c4-1111-4222-8333-444455556666",
          user_message_id: "11111111-1111-4111-8111-111111111111",
          assistant_message_id: "22222222-2222-4222-8222-222222222222",
          sources: [],
          images: [image],
        })}`,
        "",
        "",
      ].join("\n");
    const { events } = parseChatSseChunk(raw);
    expect(events).toEqual([
      {
        type: "meta",
        chat_id: "b7e1a2c4-1111-4222-8333-444455556666",
        user_message_id: "11111111-1111-4111-8111-111111111111",
        assistant_message_id: "22222222-2222-4222-8222-222222222222",
        sources: [],
        images: [image],
      },
    ]);
  });

  it("leaves an unfinished block for the next chunk", () => {
    const { events, rest } = consumeSseBuffer("event: delta\ndata: {\"content\":\"A\"}");
    expect(events).toEqual([]);
    expect(rest).toContain("content");
  });
});
