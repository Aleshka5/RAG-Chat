import { statusPresentation } from "../shared/labels";
import type { FileCard } from "../types";

export function FileStatus({ file }: { file: Pick<FileCard, "status" | "progress" | "error" | "local"> }) {
  const view = statusPresentation(file);
  const failed = view.tone === "red";
  return (
    <div>
      <span className={failed ? "status-blocked" : "status-chip"}>{view.label}</span>
      {view.hint ? <p className="hint-danger">{view.hint}</p> : null}
    </div>
  );
}
