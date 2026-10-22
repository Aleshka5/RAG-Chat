import { describe, expect, it } from "vitest";
import { applyStreamEvent, fromServerMessage, startTurn } from "./chatTurn";
import type { ChatStreamEvent } from "./sse";

const source = {
  file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  file_name: "Отчёт.pdf",
  page_number: 5,
  chunk_index: 1,
  snippet: "Срок годности",
  score: 0.8,
};

describe("chat turn", () => {
  it("shows the question before meta, then sources before the answer is finished", () => {
    let turn = startTurn([], "Каков срок годности?", "2026-10-18T20:00:00Z", "local-1");
    expect(turn.messages).toHaveLength(1);
    expect(turn.messages[0]).toMatchObject({ role: "user", pending: true, saved: false });

    const meta: ChatStreamEvent = {
      type: "meta",
      chat_id: "chat-1",
      user_message_id: "user-1",
      assistant_message_id: "assistant-1",
      sources: [source],
    };
    turn = applyStreamEvent(turn, meta, "2026-10-18T20:00:01Z");
    expect(turn.messages[0]).toMatchObject({ message_id: "user-1", pending: false, saved: false });
    expect(turn.messages[1]).toMatchObject({
      message_id: "assistant-1",
      content: "",
      sources: [source],
      saved: false,
    });

    turn = applyStreamEvent(turn, { type: "delta", content: "Не найдено в документах." }, "2026-10-18T20:00:02Z");
    expect(turn.messages[1].content).toBe("Не найдено в документах.");
    expect(turn.outcome).toBe("open");

    turn = applyStreamEvent(turn, { type: "done", finish_reason: "stop" }, "2026-10-18T20:00:03Z");
    expect(turn.outcome).toBe("saved");
    expect(turn.messages.every((message) => message.saved)).toBe(true);
    expect(turn.messages.every((message) => message.retrievalOnly === false)).toBe(true);
  });

  it("saves a retrieval-only turn with empty content and the found sources", () => {
    let turn = startTurn([], "Каков срок годности?", "2026-10-18T20:00:00Z", "local-1");
    turn = applyStreamEvent(
      turn,
      {
        type: "meta",
        chat_id: "chat-1",
        user_message_id: "user-1",
        assistant_message_id: "assistant-1",
        sources: [source],
      },
      "2026-10-18T20:00:01Z",
    );
    expect(turn.messages[1]).toMatchObject({ content: "", retrievalOnly: false, saved: false, sources: [source] });

    turn = applyStreamEvent(turn, { type: "done", finish_reason: "retrieval_only" }, "2026-10-18T20:00:02Z");
    expect(turn.outcome).toBe("saved");
    expect(turn.messages[1]).toMatchObject({
      content: "",
      retrievalOnly: true,
      saved: true,
      sources: [source],
    });
    expect(turn.messages[0].retrievalOnly).toBe(false);
  });

  it("maps finish_reason from a saved message", () => {
    const retrieval = fromServerMessage({
      message_id: "assistant-1",
      role: "assistant",
      content: "",
      sources: [source],
      finish_reason: "retrieval_only",
      created_at: "2026-10-18T20:01:02Z",
    });
    expect(retrieval.retrievalOnly).toBe(true);
    expect(retrieval.content).toBe("");
    expect(retrieval.sources).toEqual([source]);

    const ordinary = fromServerMessage({
      message_id: "assistant-2",
      role: "assistant",
      content: "Не найдено в документах.",
      sources: [],
      created_at: "2026-10-18T20:01:03Z",
    });
    expect(ordinary.retrievalOnly).toBe(false);
  });

  it("marks a broken turn unsaved and keeps the question for retry", () => {
    let turn = startTurn([], "Повтори", "2026-10-18T20:00:00Z", "local-1");
    turn = applyStreamEvent(
      turn,
      {
        type: "meta",
        chat_id: "chat-1",
        user_message_id: "user-1",
        assistant_message_id: "assistant-1",
        sources: [],
      },
      "2026-10-18T20:00:01Z",
    );
    turn = applyStreamEvent(turn, { type: "error", code: "upstream_timeout", message: "LLM timed out" }, "2026-10-18T20:00:02Z");
    expect(turn.outcome).toBe("failed");
    expect(turn.messages.every((message) => message.saved === false)).toBe(true);
    expect(turn.messages[1].errorText).toBe("The answer did not arrive in time");
    expect(turn.messages[1].retryContent).toBe("Повтори");
    expect(turn.messages[1].sources).toEqual([]);
  });
});
