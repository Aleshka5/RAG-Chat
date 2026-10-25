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
  "unsupported_image",
  "image_too_large",
  "enqueue_failed",
  "processing_attempts_exceeded",
] as const;

describe("file error labels", () => {
  it("uses the human-readable label for every processing code", () => {
    expect(FILE_ERROR_LABELS).toEqual({
      corrupt_pdf: "The file is damaged or is not a PDF",
      storage_read_failed: "Could not read the file from storage",
      embedding_failed: "Could not build the vectors",
      index_write_failed: "Could not write the index",
      metadata_update_failed: "Could not save the status",
      no_extractable_text: "No text found in the document",
      unsupported_image: "The image is damaged or is not a supported image",
      image_too_large: "The image is larger than the allowed size",
      enqueue_failed: "Could not queue the file",
      processing_attempts_exceeded: "Processing stopped several times and did not finish",
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
    expect(view.label).toBe("Processing… 2 of 10");
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
    ).toBe("Processing…");
  });

  it("separates upload size and media-type failures from a generic error", () => {
    expect(requestErrorLabel(413, "file_too_large", "Could not upload the file")).toBe(
      "The file is larger than the allowed size",
    );
    expect(requestErrorLabel(413, "", "Could not upload the file")).toBe("The file is larger than the allowed size");
    expect(requestErrorLabel(415, "unsupported_media_type", "Could not upload the file")).toBe(
      "This file type is not supported",
    );
    expect(requestErrorLabel(415, "", "Could not upload the file")).toBe("This file type is not supported");
    expect(requestErrorLabel(409, "duplicate_file", "Could not upload the file")).toBe("This file already exists");
    expect(requestErrorLabel(409, "file_busy", "Could not delete the file")).toBe(
      "Processing is still in progress or deletion has already started",
    );
    expect(requestErrorLabel(500, "", "Could not upload the file")).toBe("Could not upload the file");
  });

  it("maps stream error codes and leaves the model phrase untouched", () => {
    expect(streamErrorLabel("upstream_timeout")).toBe("The answer did not arrive in time");
    expect(streamErrorLabel("dependency_unavailable")).toBe("The service is temporarily unavailable");
    expect(streamErrorLabel("unknown_code")).toBe("Could not get an answer");
  });
});
