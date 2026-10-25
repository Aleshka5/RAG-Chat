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
    document.title = "Files · Documents · Filenkov";
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
            <p className="kicker">Documents</p>
            <h1>Files</h1>
          </div>
        </div>
        <p className="muted page-lead">Each file is uploaded in one request and processed in the background.</p>
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
        <span className="dropzone-title">Drop a PDF or an image here</span>
        <span className="dropzone-hint">or choose a file from disk</span>
        <input
          className="sr-only"
          type="file"
          accept="application/pdf,.pdf,image/jpeg,.jpg,.jpeg,image/png,.png,image/webp,.webp,image/gif,.gif"
          multiple
          disabled={uploading}
          onChange={(event) => {
            void acceptFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <span className="btn">Choose file</span>
      </label>

      {notice ? (
        <div className="banner error" role="alert">
          <p>{notice.text}</p>
          {notice.fileId ? (
            <Link className="link" to={`/files/${notice.fileId}?page=1`}>
              Open existing
            </Link>
          ) : null}
        </div>
      ) : null}
      {pollError ? (
        <div className="banner error" role="alert">
          <p>{pollError}</p>
        </div>
      ) : null}

      {phase === "loading" ? <LoadingBlock label="Loading list…" /> : null}
      {phase === "error" && errorMessage ? (
        <ErrorBlock text={errorMessage} onRetry={() => void load()} />
      ) : null}
      {phase === "ready" && items.length === 0 ? (
        <EmptyBlock
          title="No files yet"
          text="Upload a PDF or an image. After it is processed, you can ask a question about it."
        />
      ) : null}

      {items.length > 0 ? (
        <div className="table-wrap table-dense">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Status</th>
                <th>Pages</th>
                <th>Uploaded</th>
                <th>Actions</th>
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
            Showing {rangeStart}–{rangeEnd} of {total}
          </p>
          <div className="actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Back
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset + limit >= total}
              onClick={() => setOffset(offset + limit)}
            >
              Next
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
      <button type="button" className="overlay-dismiss" aria-label="No" onClick={onCancel} />
      <div className="panel">
        <h2 id="delete-file-title" ref={titleRef} tabIndex={-1}>
          Delete?
        </h2>
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            No
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            Yes
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
      <td className="cell-wrap" data-label="Name">
        {canOpen ? (
          <Link className="link" to={`/files/${file.file_id}?page=1`}>
            {file.file_name}
          </Link>
        ) : (
          <span className="file-name">{file.file_name}</span>
        )}
      </td>
      <td className="nums muted" data-label="Size">
        {formatBytes(file.file_size)}
      </td>
      <td className="cell-wrap" data-label="Status">
        <FileStatus file={file} />
      </td>
      <td className="nums" data-label="Pages">
        {formatPageCount(file.page_count)}
      </td>
      <td className="muted" data-label="Uploaded">
        {formatDateTime(file.created_at)}
      </td>
      <td data-label="Actions">
        <div className="actions">
          {file.local || file.status === "deleting" ? null : (
            <button type="button" className="btn btn-danger" onClick={onAskDelete}>
              Delete
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
