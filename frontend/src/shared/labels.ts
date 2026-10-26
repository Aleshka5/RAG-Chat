import type { FileProgress, FileStatus } from "../types";

export const FILE_ERROR_LABELS: Record<string, string> = {
  corrupt_pdf: "The file is damaged or is not a PDF",
  corrupt_document: "The file is damaged or is not a Word or Excel document",
  storage_read_failed: "Could not read the file from storage",
  embedding_failed: "Could not build the vectors",
  index_write_failed: "Could not write the index",
  metadata_update_failed: "Could not save the status",
  no_extractable_text: "No text found in the document",
  unsupported_image: "The image is damaged or is not a supported image",
  image_too_large: "The image is larger than the allowed size",
  enqueue_failed: "Could not queue the file",
  processing_attempts_exceeded: "Processing stopped several times and did not finish",
};

export const RETRIEVAL_ONLY_NOTICE = "The model is unavailable. Showing the passages that were found.";

export const REQUEST_ERROR_LABELS: Record<string, string> = {
  validation_error: "Check the values you entered",
  unauthenticated: "Sign in again",
  forbidden: "Access denied",
  blocked: "Access denied",
  unauthorized: "Sign in again",
  file_not_found: "File not found",
  chat_not_found: "Chat not found",
  duplicate_file: "This file already exists",
  file_busy: "Processing is still in progress or deletion has already started",
  file_too_large: "The file is larger than the allowed size",
  unsupported_media_type: "This file type is not supported",
  enqueue_failed: FILE_ERROR_LABELS.enqueue_failed,
  upstream_failed: "The answer service is temporarily unavailable",
  dependency_unavailable: "The service is temporarily unavailable",
  upstream_timeout: "The answer did not arrive in time",
};

export const STATUS_LABELS: Record<FileStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing…",
  ready: "Ready",
  error: "Error",
  deleting: "Deleting…",
};

export function fileErrorLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return FILE_ERROR_LABELS[code] ?? code;
}

export function requestErrorLabel(status: number, code: string, fallback: string): string {
  if (status === 413 || code === "file_too_large") return REQUEST_ERROR_LABELS.file_too_large;
  if (status === 415 || code === "unsupported_media_type") return REQUEST_ERROR_LABELS.unsupported_media_type;
  if (code === "duplicate_file") return REQUEST_ERROR_LABELS.duplicate_file;
  if (code === "file_busy") return REQUEST_ERROR_LABELS.file_busy;
  if (code && FILE_ERROR_LABELS[code]) return FILE_ERROR_LABELS[code];
  if (code && REQUEST_ERROR_LABELS[code]) return REQUEST_ERROR_LABELS[code];
  if (status === 409) return "This request cannot be completed right now";
  return fallback;
}

export function streamErrorLabel(code: string): string {
  if (code && FILE_ERROR_LABELS[code]) return FILE_ERROR_LABELS[code];
  if (code && REQUEST_ERROR_LABELS[code]) return REQUEST_ERROR_LABELS[code];
  return "Could not get an answer";
}

export type StatusTone = "yellow" | "blue" | "green" | "red" | "gray";

export type StatusPresentation = {
  label: string;
  tone: StatusTone;
  spinner: boolean;
  hint: string | null;
};

export function statusPresentation(file: {
  status: FileStatus;
  progress: FileProgress | null;
  error: string | null;
  local?: boolean;
}): StatusPresentation {
  if (file.local) {
    return { label: "Uploading…", tone: "yellow", spinner: true, hint: null };
  }
  if (file.status === "processing") {
    const label =
      file.progress && file.progress.pages_total != null
        ? `Processing… ${file.progress.pages_done} of ${file.progress.pages_total}`
        : STATUS_LABELS.processing;
    return { label, tone: "blue", spinner: true, hint: null };
  }
  if (file.status === "error") {
    return {
      label: STATUS_LABELS.error,
      tone: "red",
      spinner: false,
      hint: fileErrorLabel(file.error),
    };
  }
  const tone: Record<Exclude<FileStatus, "processing" | "error">, StatusTone> = {
    uploaded: "yellow",
    ready: "green",
    deleting: "gray",
  };
  return {
    label: STATUS_LABELS[file.status],
    tone: tone[file.status],
    spinner: false,
    hint: null,
  };
}
