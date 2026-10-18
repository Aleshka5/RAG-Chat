import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileStatus } from "../components/FileStatus";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/States";
import { formatBytes, formatDateTime, formatPageCount } from "../shared/format";
import { useFileListPolling } from "../shared/polling";
import { useFilesStore } from "../stores/filesStore";
import type { FileCard } from "../types";

export function FilesPage() {
  const items = useFilesStore((state) => state.items);
  const phase = useFilesStore((state) => state.phase);
  const errorMessage = useFilesStore((state) => state.errorMessage);
  const pollError = useFilesStore((state) => state.pollError);
  const notice = useFilesStore((state) => state.notice);
  const uploading = useFilesStore((state) => state.uploading);
  const total = useFilesStore((state) => state.total);
  const offset = useFilesStore((state) => state.offset);
  const limit = useFilesStore((state) => state.limit);
  const load = useFilesStore((state) => state.load);
  const upload = useFilesStore((state) => state.upload);
  const remove = useFilesStore((state) => state.remove);
  const setOffset = useFilesStore((state) => state.setOffset);
  const [dragOver, setDragOver] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, [load]);

  useFileListPolling(items, () => {
    void load({ silent: true });
  });

  async function acceptFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    for (const file of [...list]) {
      await upload(file);
    }
  }

  const serverCount = items.filter((item) => !item.local).length;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = total === 0 ? 0 : Math.min(offset + serverCount, total);

  return (
    <section className="space-y-5">
      <div>
        <h1 className="serif text-3xl">Файлы</h1>
        <p className="mt-1 text-muted">PDF загружается по одному запросу и обрабатывается в фоне.</p>
      </div>

      <label
        className={`block cursor-pointer rounded-2xl border-2 border-dashed px-5 py-8 text-center ${
          dragOver ? "border-pine bg-white" : "border-line bg-sheet"
        } ${uploading ? "opacity-70" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragOver(false);
          void acceptFiles(event.dataTransfer.files);
        }}
      >
        <span className="serif text-xl">Перетащите PDF сюда</span>
        <span className="mt-1 block text-sm text-muted">или выберите файл на диске</span>
        <input
          className="sr-only"
          type="file"
          accept="application/pdf,.pdf"
          multiple
          disabled={uploading}
          onChange={(event) => {
            void acceptFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <span className="mt-4 inline-flex rounded-full bg-pine px-4 py-2 text-sm text-sheet">Выбрать PDF</span>
      </label>

      {notice ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-red-950" role="alert">
          <p>{notice.text}</p>
          {notice.fileId ? (
            <Link className="mt-1 inline-flex text-sm underline" to={`/files/${notice.fileId}?page=1`}>
              Открыть существующий
            </Link>
          ) : null}
        </div>
      ) : null}
      {pollError ? <p className="text-sm text-red-900">{pollError}</p> : null}

      {phase === "loading" ? <LoadingBlock label="Загрузка списка…" /> : null}
      {phase === "error" && errorMessage ? <ErrorBlock text={errorMessage} onRetry={() => void load()} /> : null}
      {phase === "ready" && items.length === 0 ? (
        <EmptyBlock title="Файлов пока нет" text="Загрузите PDF — после обработки по нему можно будет задать вопрос." />
      ) : null}

      {items.length > 0 ? (
        <div className="overflow-hidden rounded-2xl border border-line bg-sheet">
          <div className="hidden grid-cols-[minmax(0,1.5fr)_6.5rem_13rem_5rem_9rem_auto] gap-3 border-b border-line px-4 py-2 text-xs uppercase tracking-wide text-muted md:grid">
            <span>Имя</span>
            <span>Размер</span>
            <span>Статус</span>
            <span>Страницы</span>
            <span>Загружен</span>
            <span className="sr-only">Действия</span>
          </div>
          <ul>
            {items.map((file) => (
              <FileRow
                key={file.file_id}
                file={file}
                confirming={confirmId === file.file_id}
                onAskDelete={() => setConfirmId(file.file_id)}
                onCancelDelete={() => setConfirmId(null)}
                onConfirmDelete={() => {
                  setConfirmId(null);
                  void remove(file.file_id);
                }}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {total > limit ? (
        <div className="flex items-center justify-between gap-3 text-sm">
          <p className="text-muted">
            Показаны {rangeStart}–{rangeEnd} из {total}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded-full border border-line bg-sheet px-3 py-1.5 disabled:opacity-40"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Назад
            </button>
            <button
              type="button"
              className="rounded-full border border-line bg-sheet px-3 py-1.5 disabled:opacity-40"
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
            >
              Дальше
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function FileRow({
  file,
  confirming,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  file: FileCard;
  confirming: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const canOpen = !file.local && file.status !== "deleting";
  return (
    <li className="grid gap-3 border-b border-line px-4 py-3 last:border-b-0 md:grid-cols-[minmax(0,1.5fr)_6.5rem_13rem_5rem_9rem_auto] md:items-center">
      <div className="min-w-0">
        {canOpen ? (
          <Link className="truncate font-medium text-pine underline-offset-2 hover:underline" to={`/files/${file.file_id}?page=1`}>
            {file.file_name}
          </Link>
        ) : (
          <p className="truncate font-medium">{file.file_name}</p>
        )}
      </div>
      <p className="text-sm text-muted">{formatBytes(file.file_size)}</p>
      <FileStatus file={file} />
      <p className="text-sm">{formatPageCount(file.page_count)}</p>
      <p className="text-sm text-muted">{formatDateTime(file.created_at)}</p>
      <div className="flex flex-wrap items-center gap-2">
        {file.local || file.status === "deleting" ? null : confirming ? (
          <>
            <span className="text-sm">Удалить?</span>
            <button type="button" className="rounded-full bg-red-800 px-3 py-1 text-sm text-white" onClick={onConfirmDelete}>
              Да
            </button>
            <button type="button" className="rounded-full border border-line px-3 py-1 text-sm" onClick={onCancelDelete}>
              Нет
            </button>
          </>
        ) : (
          <button type="button" className="rounded-full border border-line px-3 py-1 text-sm" onClick={onAskDelete}>
            Удалить
          </button>
        )}
      </div>
    </li>
  );
}
