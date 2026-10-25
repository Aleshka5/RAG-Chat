import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect(screen.queryByText("The model is unavailable. Showing the passages that were found.")).toBeNull();
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

    expect(await screen.findByText("The model is unavailable. Showing the passages that were found.")).toBeTruthy();
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
    expect(screen.queryByText("The model is unavailable. Showing the passages that were found.")).toBeNull();
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
    expect(await screen.findByText("Could not load chats")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(
      screen.getByText("Choose a chat or start a new one. History is stored on the server and opens after a reload."),
    ).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Chats" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
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
    expect(await screen.findByText("No chats yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New chat" })).toBeTruthy();
  });

  it("confirms before deleting and closes the history sidebar", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (url.startsWith("/api/chats?")) {
        return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
      }
      if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
        return Response.json({
          ...chat,
          messages: [],
          limit: 200,
          offset: 0,
          total_messages: 0,
        });
      }
      throw new Error(url);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={[`/chat/${chat.chat_id}`]}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "Delete chat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ask" })).toBeTruthy();
    expect(screen.getByLabelText("Question")).toBeTruthy();
    expect(screen.getByPlaceholderText("Ask about the documents")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Chats" }));
    const history = document.getElementById("chat-history");
    expect(history?.className).toContain("is-open");
    expect(screen.getAllByRole("button", { name: "Close" }).length).toBe(2);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(history?.className).not.toContain("is-open");

    fireEvent.click(screen.getByRole("button", { name: "Chats" }));
    fireEvent.click(document.querySelector(".chat-history-scrim") as HTMLButtonElement);
    expect(history?.className).not.toContain("is-open");

    fireEvent.click(screen.getByRole("button", { name: "Chats" }));
    fireEvent.click(screen.getByRole("button", { name: /Каков срок годности/ }));
    expect(history?.className).not.toContain("is-open");

    fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    expect(fetchMock.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === "DELETE")).toBe(false);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === "DELETE")).toBe(
        true,
      );
    });
  });

  it("reveals one row delete control when the pointer is coarse", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(pointer: coarse)",
      media: query,
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return false;
      },
    }));
    const other = {
      ...chat,
      chat_id: "c7e1a2c4-1111-4222-8333-444455556667",
      title: "Другой чат",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.startsWith("/api/chats?")) {
          return Response.json({ items: [chat, other], limit: 50, offset: 0, total: 2 });
        }
        if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
          return Response.json({ ...chat, messages: [], limit: 200, offset: 0, total_messages: 0 });
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

    const first = await screen.findByRole("button", { name: /Каков срок годности/ });
    const second = screen.getByRole("button", { name: /Другой чат/ });
    fireEvent.click(first);
    expect(first.closest("li")?.classList.contains("is-armed")).toBe(true);
    expect(second.closest("li")?.classList.contains("is-armed")).toBe(false);
    expect(first.getAttribute("aria-current")).toBe("page");
    fireEvent.click(second);
    expect(first.closest("li")?.classList.contains("is-armed")).toBe(false);
    expect(second.closest("li")?.classList.contains("is-armed")).toBe(true);
    expect(second.getAttribute("aria-current")).toBeNull();
  });

  it("sends documents mode without a mode field and still renders source cards", async () => {
    const source = {
      file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
      file_name: "Отчёт.pdf",
      page_number: 5,
      chunk_index: 1,
      snippet: "Срок годности",
      score: 0.8,
    };
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST") {
          bodies.push(String(init.body));
          return new Response(messageStream("Ответ из документов.", [source]), {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (url.startsWith("/api/chats?")) {
          return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
        }
        if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
          return Response.json({
            ...chat,
            messages: [
              {
                message_id: "22222222-2222-4222-8222-222222222222",
                role: "assistant",
                content: "Ответ из документов.",
                sources: [source],
                created_at: "2026-10-18T20:01:02Z",
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

    expect(await screen.findByText("Page 5")).toBeTruthy();
    expect(screen.getByText("Отчёт.pdf")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      "/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f?page=5",
    );
    expect(document.querySelector(".image-hit")).toBeNull();
    expect(screen.getByRole("button", { name: "Documents" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Каков срок годности?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => {
      expect(bodies.length).toBeGreaterThan(0);
    });
    expect(JSON.parse(bodies[0] ?? "{}")).toEqual({ content: "Каков срок годности?" });
    expect(screen.getByText("Page 5")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("sends image search mode and renders image hits from a reloaded chat", async () => {
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:image-hit");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const image = {
      file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
      file_name: "a.jpg",
      score: 0.77,
      content_path: "/api/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/content",
    };
    const bodies: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") {
        bodies.push(String(init.body));
        return new Response(messageStream("Найдено изображений: 1.", [], [image]), {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (url.endsWith("/content")) {
        return new Response(new Uint8Array([0xff, 0xd8, 0xff]), {
          status: 200,
          headers: { "Content-Type": "image/jpeg" },
        });
      }
      if (url.startsWith("/api/chats?")) {
        return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
      }
      if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
        return Response.json({
          ...chat,
          messages: [
            {
              message_id: "22222222-2222-4222-8222-222222222222",
              role: "assistant",
              content: "Найдено изображений: 1.",
              sources: [],
              images: [image],
              created_at: "2026-10-18T20:01:02Z",
            },
          ],
          limit: 200,
          offset: 0,
          total_messages: 1,
        });
      }
      throw new Error(url);
    });
    vi.stubGlobal("fetch", fetchMock);

    const view = render(
      <MemoryRouter initialEntries={[`/chat/${chat.chat_id}`]}>
        <Routes>
          <Route path="/chat/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Найдено изображений: 1.")).toBeTruthy();
    expect(screen.getByText("a.jpg")).toBeTruthy();
    expect(screen.getByText("Score 0.77")).toBeTruthy();
    const thumb = await waitFor(() => {
      const img = document.querySelector(".image-hit img");
      expect(img).toBeTruthy();
      return img as HTMLImageElement;
    });
    expect(thumb.getAttribute("src")).toBe("blob:image-hit");
    expect(thumb.getAttribute("src")).not.toContain("/api/files/");
    expect(screen.queryByText(/Page /)).toBeNull();
    expect(fetchMock.mock.calls.some((call) => String(call[0]) === image.content_path)).toBe(true);
    expect(createObjectURL).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Images" }));
    expect(screen.getByRole("button", { name: "Images" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByPlaceholderText("Search images")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "схема узла" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => {
      expect(bodies.length).toBeGreaterThan(0);
    });
    expect(JSON.parse(bodies[0] ?? "{}")).toEqual({ content: "схема узла", mode: "images" });

    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:image-hit");
  });

  it("shows an empty image result without a thumbnail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("/api/chats?")) {
          return Response.json({ items: [chat], limit: 50, offset: 0, total: 1 });
        }
        if (url.startsWith(`/api/chats/${chat.chat_id}`)) {
          return Response.json({
            ...chat,
            messages: [
              {
                message_id: "22222222-2222-4222-8222-222222222222",
                role: "assistant",
                content: "Не найдено изображений.",
                sources: [],
                images: [],
                created_at: "2026-10-18T20:01:02Z",
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

    expect(await screen.findByText("Не найдено изображений.")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector(".image-hit")).toBeNull();
  });
});

function messageStream(text: string, sources: unknown[], images?: unknown[]): string {
  const meta: Record<string, unknown> = {
    chat_id: chat.chat_id,
    user_message_id: "33333333-3333-4333-8333-333333333333",
    assistant_message_id: "44444444-4444-4444-8444-444444444444",
    sources,
  };
  if (images) meta.images = images;
  return [
    "event: meta",
    `data: ${JSON.stringify(meta)}`,
    "",
    "event: delta",
    `data: ${JSON.stringify({ content: text })}`,
    "",
    "event: done",
    'data: {"finish_reason":"stop"}',
    "",
    "",
  ].join("\n");
}
