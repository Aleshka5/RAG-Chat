import { describe, expect, it } from "vitest";
import {
  FILE_ERROR_LABELS,
  requestErrorLabel,
  statusPresentation,
  streamErrorLabel,
} from "./labels";

const CODES = [
  "corrupt_pdf",
  "storage_read_failed",
  "embedding_failed",
  "index_write_failed",
  "metadata_update_failed",
  "no_extractable_text",
  "enqueue_failed",
  "processing_attempts_exceeded",
] as const;

describe("file error labels", () => {
  it("uses the human-readable label for every processing code", () => {
    expect(FILE_ERROR_LABELS).toEqual({
      corrupt_pdf: "Файл повреждён или не является PDF",
      storage_read_failed: "Не удалось прочитать файл из хранилища",
      embedding_failed: "Не удалось построить векторы",
      index_write_failed: "Не удалось записать индекс",
      metadata_update_failed: "Не удалось сохранить статус",
      no_extractable_text: "В документе не найден текст",
      enqueue_failed: "Не удалось поставить файл в очередь",
      processing_attempts_exceeded: "Обработка несколько раз прервалась и не завершилась",
    });
    for (const code of CODES) {
      expect(statusPresentation({ status: "error", progress: null, error: code }).hint).toBe(FILE_ERROR_LABELS[code]);
    }
  });

  it("shows processing progress when pages_total is present", () => {
    const view = statusPresentation({
      status: "processing",
      progress: { pages_done: 2, pages_total: 10, chunks_done: 0, chunks_total: null },
      error: null,
    });
    expect(view.label).toBe("Обработка… 2 из 10");
    expect(view.spinner).toBe(true);
    expect(view.tone).toBe("blue");
  });

  it("keeps the plain processing label when the page total is unknown", () => {
    expect(
      statusPresentation({
        status: "processing",
        progress: { pages_done: 1, pages_total: null, chunks_done: 0, chunks_total: null },
        error: null,
      }).label,
    ).toBe("Обработка…");
  });

  it("separates upload size and media-type failures from a generic error", () => {
    expect(requestErrorLabel(413, "file_too_large", "Не удалось загрузить файл")).toBe("Файл больше допустимого размера");
    expect(requestErrorLabel(413, "", "Не удалось загрузить файл")).toBe("Файл больше допустимого размера");
    expect(requestErrorLabel(415, "unsupported_media_type", "Не удалось загрузить файл")).toBe("Это не PDF");
    expect(requestErrorLabel(415, "", "Не удалось загрузить файл")).toBe("Это не PDF");
    expect(requestErrorLabel(409, "duplicate_file", "Не удалось загрузить файл")).toBe("Такой документ уже есть");
    expect(requestErrorLabel(409, "file_busy", "Не удалось удалить файл")).toBe(
      "Обработка ещё идёт или удаление уже запущено",
    );
    expect(requestErrorLabel(500, "", "Не удалось загрузить файл")).toBe("Не удалось загрузить файл");
  });

  it("maps stream error codes and leaves the model phrase untouched", () => {
    expect(streamErrorLabel("upstream_timeout")).toBe("Ответ не успел прийти");
    expect(streamErrorLabel("dependency_unavailable")).toBe("Сервис временно недоступен");
    expect(streamErrorLabel("unknown_code")).toBe("Не удалось получить ответ");
  });
});
