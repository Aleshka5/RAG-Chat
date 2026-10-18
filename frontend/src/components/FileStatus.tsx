import { statusPresentation, type StatusTone } from "../shared/labels";
import type { FileCard } from "../types";

const TONE: Record<StatusTone, string> = {
  yellow: "bg-amber-100 text-amber-950",
  blue: "bg-sky-100 text-sky-950",
  green: "bg-emerald-100 text-emerald-950",
  red: "bg-red-100 text-red-950",
  gray: "bg-stone-200 text-stone-700",
};

export function FileStatus({ file }: { file: Pick<FileCard, "status" | "progress" | "error" | "local"> }) {
  const view = statusPresentation(file);
  return (
    <div>
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm ${TONE[view.tone]}`}>
        {view.spinner ? (
          <span
            className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-r-transparent"
            aria-hidden="true"
          />
        ) : null}
        {view.label}
      </span>
      {view.hint ? <p className="mt-1 max-w-xs text-sm text-red-900">{view.hint}</p> : null}
    </div>
  );
}
