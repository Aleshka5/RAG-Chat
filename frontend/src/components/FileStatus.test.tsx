import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FileStatus } from "./FileStatus";

describe("FileStatus", () => {
  it("renders the error-code label on the file row", () => {
    render(
      <FileStatus
        file={{
          status: "error",
          progress: null,
          error: "corrupt_pdf",
        }}
      />,
    );
    expect(screen.getByText("Ошибка")).toBeTruthy();
    expect(screen.getByText("Файл повреждён или не является PDF")).toBeTruthy();
  });

  it("renders processing progress with a spinner label", () => {
    render(
      <FileStatus
        file={{
          status: "processing",
          error: null,
          progress: { pages_done: 2, pages_total: 10, chunks_done: 1, chunks_total: 4 },
        }}
      />,
    );
    expect(screen.getByText("Обработка… 2 из 10")).toBeTruthy();
  });
});
