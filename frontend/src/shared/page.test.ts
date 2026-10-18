import { describe, expect, it } from "vitest";
import { clampPage, fileContentPath, parsePageParam } from "./page";

describe("preview page numbers", () => {
  it("replaces a page below 1 with 1 and clamps to the last page", () => {
    expect(parsePageParam(null)).toBe(1);
    expect(parsePageParam("0")).toBe(1);
    expect(parsePageParam("-4")).toBe(1);
    expect(parsePageParam("3")).toBe(3);
    expect(clampPage(0, 8)).toBe(1);
    expect(clampPage(3, 8)).toBe(3);
    expect(clampPage(40, 8)).toBe(8);
    expect(clampPage(40, null)).toBe(40);
  });

  it("does not put the page number on the content URL", () => {
    expect(fileContentPath("6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f")).toBe(
      "/api/files/6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f/content",
    );
    expect(fileContentPath("6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f")).not.toContain("page");
  });
});
