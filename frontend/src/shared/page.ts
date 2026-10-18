export function parsePageParam(value: string | null): number {
  if (value == null || value.trim() === "") return 1;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return Math.floor(parsed);
}

export function clampPage(requested: number, pageCount: number | null): number {
  const page = !Number.isFinite(requested) || requested < 1 ? 1 : Math.floor(requested);
  if (pageCount == null || pageCount < 1) return page;
  return Math.min(page, pageCount);
}

export function fileContentPath(fileId: string): string {
  return `/api/files/${encodeURIComponent(fileId)}/content`;
}
