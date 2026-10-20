import type { FileProgress, FileStatus } from "../types";

export const FILE_ERROR_LABELS: Record<string, string> = {
  corrupt_pdf: "Файл повреждён или не является PDF",
  storage_read_failed: "Не удалось прочитать файл из хранилища",
  embedding_failed: "Не удалось построить векторы",
  index_write_failed: "Не удалось записать индекс",
  metadata_update_failed: "Не удалось сохранить статус",
  no_extractable_text: "В документе не найден текст",
  enqueue_failed: "Не удалось поставить файл в очередь",
  processing_attempts_exceeded: "Обработка несколько раз прервалась и не завершилась",
};

export const RETRIEVAL_ONLY_NOTICE = "Модель недоступна. Показаны найденные фрагменты.";

export const REQUEST_ERROR_LABELS: Record<string, string> = {
  validation_error: "Проверьте введённые данные",
  unauthenticated: "Нужна повторная авторизация",
  forbidden: "Доступ закрыт",
  blocked: "Доступ закрыт",
  unauthorized: "Нужна повторная авторизация",
  file_not_found: "Файл не найден",
  chat_not_found: "Чат не найден",
  duplicate_file: "Такой документ уже есть",
  file_busy: "Обработка ещё идёт или удаление уже запущено",
  file_too_large: "Файл больше допустимого размера",
  unsupported_media_type: "Это не PDF",
  enqueue_failed: FILE_ERROR_LABELS.enqueue_failed,
  upstream_failed: "Сервис ответа временно недоступен",
  dependency_unavailable: "Сервис временно недоступен",
  upstream_timeout: "Ответ не успел прийти",
};

export const STATUS_LABELS: Record<FileStatus, string> = {
  uploaded: "Загружен",
  processing: "Обработка…",
  ready: "Готов",
  error: "Ошибка",
  deleting: "Удаление…",
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
  if (status === 409) return "Запрос сейчас нельзя выполнить";
  return fallback;
}

export function streamErrorLabel(code: string): string {
  if (code && FILE_ERROR_LABELS[code]) return FILE_ERROR_LABELS[code];
  if (code && REQUEST_ERROR_LABELS[code]) return REQUEST_ERROR_LABELS[code];
  return "Не удалось получить ответ";
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
    return { label: "Загрузка…", tone: "yellow", spinner: true, hint: null };
  }
  if (file.status === "processing") {
    const label =
      file.progress && file.progress.pages_total != null
        ? `Обработка… ${file.progress.pages_done} из ${file.progress.pages_total}`
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
