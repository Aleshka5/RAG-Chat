import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { resetSessionStore, useSessionStore } from "../stores/sessionStore";
import { SourceCard } from "./SourceCard";

const source = {
  file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  file_name: "Отчёт.pdf",
  page_number: 5,
  chunk_index: 3,
  snippet: "Срок годности составляет 12 месяцев",
  score: 0.81,
};

describe("SourceCard", () => {
  beforeEach(() => {
    resetSessionStore();
  });

  it("links to the PDF page", () => {
    render(
      <MemoryRouter>
        <SourceCard source={source} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Отчёт.pdf")).toBeTruthy();
    expect(screen.getByText("Page 5")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      "/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f?page=5",
    );
  });

  it("shows the unit label instead of the page number", () => {
    render(
      <MemoryRouter>
        <SourceCard source={{ ...source, file_name: "Отчёт.docx", unit_label: "Введение" }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Отчёт.docx")).toBeTruthy();
    expect(screen.getByText("Введение")).toBeTruthy();
    expect(screen.queryByText("Page 5")).toBeNull();
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      "/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f?page=5",
    );
  });

  it("keeps the card and says the preview is unavailable", () => {
    useSessionStore.getState().markPreviewUnavailable(source.file_id);
    render(
      <MemoryRouter>
        <SourceCard source={source} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Отчёт.pdf")).toBeTruthy();
    expect(screen.getByText("Preview unavailable")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Open" })).toBeNull();
  });
});
