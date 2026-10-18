export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "—";
  if (size < 1024) return `${Math.round(size)} Б`;
  const units = ["КБ", "МБ", "ГБ", "ТБ"];
  let value = size / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  const digits = value >= 10 ? 0 : 1;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(value)} ${units[index]}`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatPageCount(pageCount: number | null): string {
  if (pageCount == null) return "—";
  return String(pageCount);
}
