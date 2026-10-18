import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

let configured = false;

export function configurePdfWorker(): void {
  if (configured) return;
  GlobalWorkerOptions.workerSrc = workerUrl;
  configured = true;
}

export async function openPdf(data: ArrayBuffer): Promise<PDFDocumentProxy> {
  configurePdfWorker();
  return getDocument({ data: new Uint8Array(data) }).promise;
}

export async function renderPdfPage(
  pdf: PDFDocumentProxy,
  pageNumber: number,
  canvas: HTMLCanvasElement,
  maxWidth: number,
): Promise<RenderTask> {
  const page = await pdf.getPage(pageNumber);
  const unscaled = page.getViewport({ scale: 1 });
  const width = Math.max(maxWidth, 280);
  const scale = Math.min(width / unscaled.width, 2);
  const viewport = page.getViewport({ scale });
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return page.render({ canvasContext: context, viewport });
}
