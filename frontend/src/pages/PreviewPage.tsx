import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { fetchFileContent, getFile } from "../api/files";
import { AccessBlockedError, ApiError, AuthRedirectError, PreviewUnavailableError } from "../api/client";
import { ErrorBlock, LoadingBlock } from "../components/States";
import { requestErrorLabel } from "../shared/labels";
import { clampPage, parsePageParam } from "../shared/page";
import { openPdf, renderPdfPage } from "../pdf/document";
import { useSessionStore } from "../stores/sessionStore";
import { RenderingCancelledException, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";

type Phase = "loading" | "ready" | "unavailable" | "error";

export default function PreviewPage() {
  const { fileId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = parsePageParam(searchParams.get("page"));
  const markPreviewUnavailable = useSessionStore((state) => state.markPreviewUnavailable);
  const [phase, setPhase] = useState<Phase>("loading");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [numPages, setNumPages] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const documentRef = useRef<PDFDocumentProxy | null>(null);

  useEffect(() => {
    document.title = `${fileName || "Document"} · Documents · Filenkov`;
  }, [fileName]);

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setErrorText(null);
    setNumPages(null);
    setFileName("");
    const previous = documentRef.current;
    documentRef.current = null;
    void previous?.destroy();

    void (async () => {
      try {
        const [meta, bytes] = await Promise.all([
          getFile(fileId, controller.signal).catch((error: unknown) => {
            if (error instanceof PreviewUnavailableError || (error instanceof ApiError && error.status === 404)) {
              return null;
            }
            throw error;
          }),
          fetchFileContent(fileId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        if (meta) setFileName(meta.file_name);
        const pdf = await openPdf(bytes);
        if (controller.signal.aborted) {
          await pdf.destroy();
          return;
        }
        documentRef.current = pdf;
        setNumPages(pdf.numPages);
        setPhase("ready");
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof PreviewUnavailableError || (error instanceof ApiError && error.status === 404)) {
          markPreviewUnavailable(fileId);
          setPhase("unavailable");
          return;
        }
        if (error instanceof AccessBlockedError || error instanceof AuthRedirectError) return;
        const text =
          error instanceof ApiError
            ? requestErrorLabel(error.status, error.code, "Could not open the document")
            : "Could not open the document";
        setErrorText(text);
        setPhase("error");
      }
    })();

    return () => {
      controller.abort();
    };
  }, [fileId, reloadKey, markPreviewUnavailable]);

  useEffect(() => {
    return () => {
      const pdf = documentRef.current;
      documentRef.current = null;
      void pdf?.destroy();
    };
  }, []);

  const page = clampPage(requested, numPages);

  useEffect(() => {
    if (numPages == null) return;
    if (requested !== page) {
      setSearchParams({ page: String(page) }, { replace: true });
    }
  }, [numPages, requested, page, setSearchParams]);

  useEffect(() => {
    const pdf = documentRef.current;
    const canvas = canvasRef.current;
    const frame = frameRef.current;
    if (phase !== "ready" || !pdf || !canvas || !frame || numPages == null) return;
    let cancelled = false;
    let generation = 0;
    let task: RenderTask | null = null;
    const draw = () => {
      const current = ++generation;
      task?.cancel();
      const width = frame.clientWidth;
      void renderPdfPage(pdf, page, canvas, width)
        .then((next) => {
          if (cancelled || current !== generation) {
            next.cancel();
            return undefined;
          }
          task = next;
          return next.promise;
        })
        .catch((error: unknown) => {
          if (cancelled || current !== generation || error instanceof RenderingCancelledException) return;
          setErrorText("Could not show the page");
          setPhase("error");
        });
    };
    draw();
    const observer = new ResizeObserver(() => draw());
    observer.observe(frame);
    return () => {
      cancelled = true;
      task?.cancel();
      observer.disconnect();
    };
  }, [phase, page, numPages, fileId]);

  function goTo(next: number) {
    const target = clampPage(next, numPages);
    setSearchParams({ page: String(target) }, { replace: true });
  }

  return (
    <section className="view-in screen">
      <div className="page-head">
        <div>
          <Link className="up" to="/files">
            Back to files
          </Link>
          <p className="kicker">Documents</p>
          <h1>{fileName || "Document"}</h1>
        </div>
        {phase === "ready" && numPages != null ? (
          <div className="actions">
            <button type="button" className="btn btn-ghost" disabled={page <= 1} onClick={() => goTo(page - 1)}>
              Back
            </button>
            <p className="meta nums">
              Page {page} of {numPages}
            </p>
            <button type="button" className="btn btn-ghost" disabled={page >= numPages} onClick={() => goTo(page + 1)}>
              Next
            </button>
          </div>
        ) : null}
      </div>

      {phase === "loading" ? <LoadingBlock label="Opening PDF…" /> : null}
      {phase === "unavailable" ? (
        <div className="surface stack" role="status">
          <h2>Preview unavailable</h2>
          <p className="muted">The file has already been deleted or cannot be shown.</p>
        </div>
      ) : null}
      {phase === "error" && errorText ? (
        <ErrorBlock text={errorText} onRetry={() => setReloadKey((value) => value + 1)} />
      ) : null}
      <div ref={frameRef} className={phase === "ready" ? "sheet-frame" : "sheet-frame is-hidden"}>
        <canvas ref={canvasRef} />
      </div>
    </section>
  );
}
