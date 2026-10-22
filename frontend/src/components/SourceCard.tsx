import { Link } from "react-router-dom";
import { useSessionStore } from "../stores/sessionStore";
import type { Source } from "../types";

export function SourceCard({ source }: { source: Source }) {
  const unavailable = useSessionStore((state) => state.unavailableFileIds.includes(source.file_id));
  return (
    <article className="source-card">
      <p className="choice-title truncate">{source.file_name}</p>
      <p className="meta">стр. {source.page_number}</p>
      {source.snippet ? <p className="choice-teaser">{source.snippet}</p> : null}
      {unavailable ? (
        <p className="hint-danger">Предпросмотр недоступен</p>
      ) : (
        <Link className="link" to={`/files/${source.file_id}?page=${source.page_number}`}>
          Открыть
        </Link>
      )}
    </article>
  );
}
