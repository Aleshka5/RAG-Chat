import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
    document.title = "Файлы · Документы · Filenkov";
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!confirmId) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setConfirmId(null);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [confirmId]);

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
    <section className="view-in screen">
      <div>
        <div className="page-head">
          <div>
            <p className="kicker">Документы</p>
            <h1>Файлы</h1>
          </div>
        </div>
        <p className="muted page-lead">PDF загружается по одному запросу и обрабатывается в фоне.</p>
      </div>

      <label
        className={`dropzone${dragOver ? " is-active" : ""}${uploading ? " is-disabled" : ""}`}
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
        <span className="dropzone-title">Перетащите PDF сюда</span>
        <span className="dropzone-hint">или выберите файл на диске</span>
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
        <span className="btn">Выбрать PDF</span>
      </label>

      {notice ? (
        <div className="banner error" role="alert">
          <p>{notice.text}</p>
          {notice.fileId ? (
            <Link className="link" to={`/files/${notice.fileId}?page=1`}>
              Открыть существующий
            </Link>
          ) : null}
        </div>
      ) : null}
      {pollError ? (
        <div className="banner error" role="alert">
          <p>{pollError}</p>
        </div>
      ) : null}

      {phase === "loading" ? <LoadingBlock label="Загрузка списка…" /> : null}
      {phase === "error" && errorMessage ? (
        <ErrorBlock text={errorMessage} onRetry={() => void load()} />
      ) : null}
      {phase === "ready" && items.length === 0 ? (
        <EmptyBlock
          title="Файлов пока нет"
          text="Загрузите PDF — после обработки по нему можно будет задать вопрос."
        />
      ) : null}

      {items.length > 0 ? (
        <div className="table-wrap table-dense">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>Размер</th>
                <th>Статус</th>
                <th>Страницы</th>
                <th>Загружен</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((file) => (
                <FileRow key={file.file_id} file={file} onAskDelete={() => setConfirmId(file.file_id)} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {total > limit ? (
        <div className="pager meta">
          <p className="muted">
            Показаны {rangeStart}–{rangeEnd} из {total}
          </p>
          <div className="actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Назад
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
            >
              Дальше
            </button>
          </div>
        </div>
      ) : null}

      {confirmId
        ? createPortal(
            <DeleteFileDialog
              onCancel={() => setConfirmId(null)}
              onConfirm={() => {
                const id = confirmId;
                setConfirmId(null);
                void remove(id);
              }}
            />,
            document.body,
          )
        : null}
    </section>
  );
}

function DeleteFileDialog({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    titleRef.current?.focus();
  }, []);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="delete-file-title">
      <button type="button" className="overlay-dismiss" aria-label="Нет" onClick={onCancel} />
      <div className="panel">
        <h2 id="delete-file-title" ref={titleRef} tabIndex={-1}>
          Удалить?
        </h2>
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Нет
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            Да
          </button>
        </div>
      </div>
    </div>
  );
}

function FileRow({ file, onAskDelete }: { file: FileCard; onAskDelete: () => void }) {
  const canOpen = !file.local && file.status !== "deleting";
  return (
    <tr>
      <td className="cell-wrap" data-label="Имя">
        {canOpen ? (
          <Link className="link" to={`/files/${file.file_id}?page=1`}>
            {file.file_name}
          </Link>
        ) : (
          <span className="file-name">{file.file_name}</span>
        )}
      </td>
      <td className="nums muted" data-label="Размер">
        {formatBytes(file.file_size)}
      </td>
      <td className="cell-wrap" data-label="Статус">
        <FileStatus file={file} />
      </td>
      <td className="nums" data-label="Страницы">
        {formatPageCount(file.page_count)}
      </td>
      <td className="muted" data-label="Загружен">
        {formatDateTime(file.created_at)}
      </td>
      <td data-label="Действия">
        <div className="actions">
          {file.local || file.status === "deleting" ? null : (
            <button type="button" className="btn btn-danger" onClick={onAskDelete}>
              Удалить
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
