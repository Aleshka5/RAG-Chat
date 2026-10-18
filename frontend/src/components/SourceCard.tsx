import { Link } from "react-router-dom";
import { useSessionStore } from "../stores/sessionStore";
import type { Source } from "../types";

export function SourceCard({ source }: { source: Source }) {
  const unavailable = useSessionStore((state) => state.unavailableFileIds.includes(source.file_id));
  return (
    <article className="rounded-xl border border-line bg-paper px-3 py-2">
      <p className="truncate font-medium">{source.file_name}</p>
      <p className="text-sm text-muted">стр. {source.page_number}</p>
      {source.snippet ? <p className="mt-1 line-clamp-3 text-sm text-ink/80">{source.snippet}</p> : null}
      {unavailable ? (
        <p className="mt-2 text-sm text-red-900">Предпросмотр недоступен</p>
      ) : (
        <Link
          className="mt-2 inline-flex text-sm font-medium text-pine underline decoration-pine/40 underline-offset-2"
          to={`/files/${source.file_id}?page=${source.page_number}`}
        >
          Открыть
        </Link>
      )}
    </article>
  );
}
