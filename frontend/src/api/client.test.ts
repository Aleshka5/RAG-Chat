import { beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "../shared/auth";
import { resetSessionStore, useSessionStore } from "../stores/sessionStore";
import { apiFetch, sanitizeHeaders } from "./client";

describe("api client", () => {
  beforeEach(() => {
    resetSessionStore();
  });

  it("strips identity headers and sends the session cookie", async () => {
    const headers = sanitizeHeaders(
      new Headers({
        Authorization: "Bearer secret",
        "X-User-Id": "user",
        "X-Auth-User-Id": "6f1c0c3e-3c8a-4f0e-9a4a-1d2b3c4d5e6f",
        "X-Auth-Role": "ADMIN",
        Accept: "application/json",
      }),
    );
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("x-user-id")).toBeNull();
    expect(headers.get("x-auth-user-id")).toBeNull();
    expect(headers.get("x-auth-role")).toBeNull();
    expect(headers.get("accept")).toBe("application/json");

    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ items: [], limit: 50, offset: 0, total: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/files", { headers: { Authorization: "Bearer secret", Accept: "application/json" } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/files");
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).get("authorization")).toBeNull();
  });

  it("sends the browser to the gateway login on the gateway 401 body", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ error: "unauthorized" }, { status: 401 })),
    );
    await expect(apiFetch("/api/files")).rejects.toThrow("unauthorized");
    expect(assign).toHaveBeenCalledTimes(1);
    const target = String(assign.mock.calls[0][0]);
    expect(target).toContain("/auth?return_to=");
    expect(useSessionStore.getState().blocked).toBe(false);
  });

  it("does not treat a RAG 401 envelope as the gateway redirect", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          Response.json(
            { error: { code: "unauthenticated", message: "Missing or invalid X-Auth-User-Id" } },
            { status: 401 },
          ),
      ),
    );
    const response = await apiFetch("/api/files");
    expect(response.status).toBe(401);
    expect(assign).not.toHaveBeenCalled();
  });

  it("stops on a blocked session and does not retry by itself", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: "blocked" }, { status: 403 })));
    await expect(apiFetch("/api/chats")).rejects.toThrow("blocked");
    expect(useSessionStore.getState().blocked).toBe(true);

    resetSessionStore();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          Response.json({ error: { code: "forbidden", message: "User is blocked" } }, { status: 403 }),
      ),
    );
    await expect(apiFetch("/api/chats")).rejects.toThrow("blocked");
    expect(useSessionStore.getState().blocked).toBe(true);
  });
});
