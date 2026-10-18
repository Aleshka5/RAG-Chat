import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetFilesStore } from "../stores/filesStore";
import { resetSessionStore } from "../stores/sessionStore";
import { FilesPage } from "./FilesPage";

const file = {
  file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  file_name: "Отчёт.pdf",
  file_size: 2048,
  status: "error",
  page_count: null,
  error: "no_extractable_text",
  progress: null,
  created_at: "2026-10-18T20:00:00Z",
  updated_at: "2026-10-18T20:00:00Z",
};

describe("FilesPage", () => {
  beforeEach(() => {
    resetFilesStore();
    resetSessionStore();
  });

  it("shows the empty, error and loaded states from the server list", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => {
      throw new TypeError("network");
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = render(
      <MemoryRouter>
        <FilesPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Не удалось загрузить список файлов")).toBeTruthy();
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/files?limit=50&offset=0");
    first.unmount();

    resetFilesStore();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          items: [],
          limit: 50,
          offset: 0,
          total: 0,
        }),
      ),
    );
    const second = render(
      <MemoryRouter>
        <FilesPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Файлов пока нет")).toBeTruthy();
    second.unmount();

    resetFilesStore();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          items: [file],
          limit: 50,
          offset: 0,
          total: 1,
        }),
      ),
    );
    render(
      <MemoryRouter>
        <FilesPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Отчёт.pdf")).toBeTruthy();
    expect(screen.getByText("В документе не найден текст")).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy();
  });
});
