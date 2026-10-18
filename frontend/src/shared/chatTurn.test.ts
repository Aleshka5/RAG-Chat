import { describe, expect, it } from "vitest";
import { applyStreamEvent, startTurn } from "./chatTurn";
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
    expect(turn.messages[1].errorText).toBe("Ответ не успел прийти");
    expect(turn.messages[1].retryContent).toBe("Повтори");
    expect(turn.messages[1].sources).toEqual([]);
  });
});
