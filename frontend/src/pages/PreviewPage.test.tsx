import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetSessionStore } from "../stores/sessionStore";
import PreviewPage from "./PreviewPage";

const fileId = "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f";

const { openPdf, renderPdfPage } = vi.hoisted(() => ({
  openPdf: vi.fn(),
  renderPdfPage: vi.fn(),
}));

vi.mock("../pdf/document", () => ({
  openPdf,
  renderPdfPage,
}));

const file = {
  file_id: fileId,
  file_name: "Скан.pdf",
  file_size: 2048,
  status: "ready",
  page_count: 9,
  error: null,
  progress: null,
  created_at: "2026-10-18T20:00:00Z",
  updated_at: "2026-10-18T20:00:00Z",
};

describe("PreviewPage", () => {
  beforeEach(() => {
    resetSessionStore();
    openPdf.mockReset();
    openPdf.mockResolvedValue({
      numPages: 9,
      destroy: vi.fn(async () => undefined),
    });
    renderPdfPage.mockReset();
    renderPdfPage.mockResolvedValue({
      cancel: vi.fn(),
      promise: Promise.resolve(),
    });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
  });

  it("loads GET /api/files/{id}/content and renders the page from the query", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        urls.push(url);
        if (url.includes("/content")) {
          return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          });
        }
        return Response.json(file);
      }),
    );

    render(
      <MemoryRouter initialEntries={[`/files/${fileId}?page=4`]}>
        <Routes>
          <Route path="/files/:fileId" element={<PreviewPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Скан.pdf" })).toBeTruthy();
    await waitFor(() => {
      expect(renderPdfPage).toHaveBeenCalled();
    });

    const contentUrl = `/api/files/${fileId}/content`;
    expect(urls).toContain(contentUrl);
    expect(urls).toContain(`/api/files/${fileId}`);
    for (const url of urls) {
      expect(url.startsWith("/api/files/")).toBe(true);
      expect(url.includes("?")).toBe(false);
      expect(url.toLowerCase()).not.toContain("page");
      expect(url.toLowerCase()).not.toContain("presign");
      expect(url.toLowerCase()).not.toContain("x-amz");
      expect(url.includes("://")).toBe(false);
    }
    expect(openPdf).toHaveBeenCalled();
    const renderedPages = renderPdfPage.mock.calls.map((call) => call[1]);
    expect(renderedPages.length).toBeGreaterThan(0);
    expect(renderedPages.every((page) => page === 4)).toBe(true);
  });
});
