import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetChatStore } from "../stores/chatStore";
import { resetSessionStore } from "../stores/sessionStore";
import { ChatPage } from "./ChatPage";

const chat = {
  chat_id: "b7e1a2c4-1111-4222-8333-444455556666",
  title: "Каков срок годности",
  created_at: "2026-10-18T20:00:00Z",
  updated_at: "2026-10-18T20:01:00Z",
};

describe("ChatPage", () => {
  beforeEach(() => {
    resetChatStore();
    resetSessionStore();
    vi.spyOn(Storage.prototype, "setItem");
  });

  it("loads chat history from the server rather than local storage", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      if (url.startsWith("/api/chats?")) {
        return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
      }
      if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
        return Response.json({
          ...chat,
          messages: [
            {
              message_id: "11111111-1111-4111-8111-111111111111",
              role: "user",
              content: "Каков срок годности?",
              created_at: "2026-10-18T20:01:00Z",
            },
            {
              message_id: "22222222-2222-4222-8222-222222222222",
              role: "assistant",
              content: "Не найдено в документах.",
              sources: [],
              created_at: "2026-10-18T20:01:02Z",
            },
          ],
          limit: 200,
          offset: 0,
          total_messages: 2,
        });
      }
      throw new Error(url);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/chat/${chat.chat_id}`]}>
        <Routes>
          <Route path="/chat/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Каков срок годности?")).toBeTruthy();
    expect(screen.getByText("Не найдено в документах.")).toBeTruthy();
    expect(screen.queryByText("Модель недоступна. Показаны найденные фрагменты.")).toBeNull();
    expect(fetchMock.mock.calls.some((call) => String(call[0]).startsWith("/api/chats"))).toBe(true);
    expect(localStorage.setItem).not.toHaveBeenCalled();
  });

  it("shows the retrieval-only notice above source cards after reload", async () => {
    const snippet = "Срок годности двенадцать месяцев";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.startsWith("/api/chats?")) {
          return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
        }
        if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
          return Response.json({
            ...chat,
            messages: [
              {
                message_id: "11111111-1111-4111-8111-111111111111",
                role: "user",
                content: "Каков срок годности?",
                created_at: "2026-10-18T20:01:00Z",
              },
              {
                message_id: "22222222-2222-4222-8222-222222222222",
                role: "assistant",
                content: "",
                finish_reason: "retrieval_only",
                sources: [
                  {
                    file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
                    file_name: "Отчёт.pdf",
                    page_number: 5,
                    chunk_index: 1,
                    snippet,
                    score: 0.8,
                  },
                ],
                created_at: "2026-10-18T20:01:02Z",
              },
            ],
            limit: 200,
            offset: 0,
            total_messages: 2,
          });
        }
        throw new Error(url);
      }),
    );

    const loaded = render(
      <MemoryRouter initialEntries={[`/chat/${chat.chat_id}`]}>
        <Routes>
          <Route path="/chat/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Модель недоступна. Показаны найденные фрагменты.")).toBeTruthy();
    expect(screen.getByText(snippet)).toBeTruthy();
    expect(screen.queryByText("…")).toBeNull();
    loaded.unmount();

    resetChatStore();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.startsWith("/api/chats?")) {
          return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
        }
        if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
          return Response.json({
            ...chat,
            messages: [
              {
                message_id: "33333333-3333-4333-8333-333333333333",
                role: "assistant",
                content: "Обычный ответ.",
                sources: [],
                created_at: "2026-10-18T20:02:00Z",
              },
            ],
            limit: 200,
            offset: 0,
            total_messages: 1,
          });
        }
        throw new Error(url);
      }),
    );

    render(
      <MemoryRouter initialEntries={[`/chat/${chat.chat_id}`]}>
        <Routes>
          <Route path="/chat/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Обычный ответ.")).toBeTruthy();
    expect(screen.queryByText("Модель недоступна. Показаны найденные фрагменты.")).toBeNull();
  });

  it("shows the empty and error states", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    const failed = render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Не удалось загрузить чаты")).toBeTruthy();
    expect(screen.getByText("Выберите чат или создайте новый. История хранится на сервере и открывается после перезагрузки.")).toBeTruthy();
    failed.unmount();

    resetChatStore();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ items: [], limit: 50, offset: 0, total: 0 })),
    );
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Чатов пока нет.")).toBeTruthy();
  });
});
