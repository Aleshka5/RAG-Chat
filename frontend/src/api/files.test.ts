import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetSessionStore } from "../stores/sessionStore";
import { isImageUpload, uploadFile } from "./files";

const card = {
  file_id: "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
  file_name: "photo.png",
  file_size: 3,
  status: "uploaded" as const,
  page_count: null,
  content_type: "image/png",
  error: null,
  progress: null,
  created_at: "2026-10-18T20:00:00Z",
  updated_at: "2026-10-18T20:00:00Z",
};

function makeFile(name: string, type: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type });
}

describe("file upload", () => {
  beforeEach(() => {
    resetSessionStore();
  });

  it("treats the four accepted image types and their extensions as images", () => {
    expect(isImageUpload(makeFile("photo.png", "image/png"))).toBe(true);
    expect(isImageUpload(makeFile("photo.jpg", "image/jpeg"))).toBe(true);
    expect(isImageUpload(makeFile("photo.webp", "image/webp"))).toBe(true);
    expect(isImageUpload(makeFile("photo.gif", "image/gif"))).toBe(true);
    expect(isImageUpload(makeFile("photo.PNG", ""))).toBe(true);
    expect(isImageUpload(makeFile("report.pdf", "application/pdf"))).toBe(false);
    expect(isImageUpload(makeFile("notes.txt", "text/plain"))).toBe(false);
  });

  it("posts an image to the image route and a PDF to the document route", async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => Response.json(card),
    );
    vi.stubGlobal("fetch", fetchMock);

    await uploadFile(makeFile("photo.png", "image/png"));
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/files/images");
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeInstanceOf(FormData);
    expect((fetchMock.mock.calls[0]?.[1]?.body as FormData).get("file")).toBeInstanceOf(File);

    await uploadFile(makeFile("report.pdf", "application/pdf"));
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("/api/files");
  });
});
