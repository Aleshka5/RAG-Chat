import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { hasUnfinishedFiles, POLL_INTERVAL_MS, useFileListPolling } from "./polling";

function Probe({ files, onPoll }: { files: { status: string }[]; onPoll: () => void }) {
  useFileListPolling(files, onPoll);
  return <p>{hasUnfinishedFiles(files) ? "polling" : "idle"}</p>;
}

describe("file list polling", () => {
  it("treats uploaded, processing and deleting as unfinished", () => {
    expect(hasUnfinishedFiles([])).toBe(false);
    expect(hasUnfinishedFiles([{ status: "ready" }, { status: "error" }])).toBe(false);
    expect(hasUnfinishedFiles([{ status: "uploaded" }])).toBe(true);
    expect(hasUnfinishedFiles([{ status: "processing" }])).toBe(true);
    expect(hasUnfinishedFiles([{ status: "deleting" }])).toBe(true);
    expect(hasUnfinishedFiles([{ status: "ready" }, { status: "deleting" }])).toBe(true);
  });

  it("polls every 5 seconds and stops when the page has no unfinished files", async () => {
    vi.useFakeTimers();
    const onPoll = vi.fn();
    const { rerender } = render(<Probe files={[{ status: "processing" }]} onPoll={onPoll} />);
    expect(screen.getByText("polling")).toBeTruthy();
    expect(onPoll).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(onPoll).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });
    expect(onPoll).toHaveBeenCalledTimes(2);

    rerender(<Probe files={[{ status: "ready" }, { status: "error" }]} onPoll={onPoll} />);
    expect(screen.getByText("idle")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
    });
    expect(onPoll).toHaveBeenCalledTimes(2);
  });
});
