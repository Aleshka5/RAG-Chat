import { useEffect, useRef } from "react";

export const POLL_INTERVAL_MS = 5000;

const UNFINISHED = new Set(["uploaded", "processing", "deleting"]);

export function hasUnfinishedFiles(files: { status: string }[]): boolean {
  return files.some((file) => UNFINISHED.has(file.status));
}

export function useFileListPolling(files: { status: string }[], refresh: () => void): void {
  const enabled = hasUnfinishedFiles(files);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!enabled) return undefined;
    const id = window.setInterval(() => {
      refreshRef.current();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [enabled]);
}
