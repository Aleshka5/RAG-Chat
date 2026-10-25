import type { DeleteAccepted, FileList, FileRecord } from "../types";
import { apiFetch, apiJson, PreviewUnavailableError, responseError } from "./client";
import { fileContentPath } from "../shared/page";

export function isImageContentType(contentType: string | null | undefined): boolean {
  if (!contentType) return false;
  const mime = contentType.split(";")[0]?.trim().toLowerCase() ?? "";
  return mime.startsWith("image/");
}

export function resolveContentPath(fileId: string, contentPath?: string): string {
  if (
    contentPath &&
    contentPath.startsWith("/api/files/") &&
    !contentPath.includes("://") &&
    !contentPath.includes("\\") &&
    !contentPath.includes("..")
  ) {
    return contentPath;
  }
  return fileContentPath(fileId);
}

export function listFiles(limit: number, offset: number): Promise<FileList> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiJson<FileList>(`/api/files?${params.toString()}`);
}

export function getFile(fileId: string, signal?: AbortSignal): Promise<FileRecord> {
  return apiJson<FileRecord>(`/api/files/${encodeURIComponent(fileId)}`, { signal });
}

const IMAGE_UPLOAD_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "gif"]);

export function isImageUpload(file: File): boolean {
  if (isImageContentType(file.type)) return true;
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf(".");
  return dot >= 0 && IMAGE_UPLOAD_EXTENSIONS.has(name.slice(dot + 1));
}

export function uploadFile(file: File): Promise<FileRecord> {
  const body = new FormData();
  body.append("file", file, file.name);
  const path = isImageUpload(file) ? "/api/files/images" : "/api/files";
  return apiJson<FileRecord>(path, { method: "POST", body });
}

export function deleteFile(fileId: string): Promise<DeleteAccepted> {
  return apiJson<DeleteAccepted>(`/api/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
}

export async function fetchFileContent(fileId: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const response = await apiFetch(fileContentPath(fileId), {
    signal,
    headers: { Accept: "application/pdf" },
  });
  if (response.status === 404) throw new PreviewUnavailableError();
  if (!response.ok) throw await responseError(response);
  return response.arrayBuffer();
}

export async function fetchContentBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await apiFetch(path, {
    signal,
    headers: { Accept: "image/*,*/*" },
  });
  if (response.status === 404) throw new PreviewUnavailableError();
  if (!response.ok) throw await responseError(response);
  return response.blob();
}
