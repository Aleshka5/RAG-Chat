import { describe, expect, it } from "vitest";
import { isAccessBlocked, isGatewayUnauthorized, loginUrl } from "./auth";

describe("gateway auth", () => {
  it("recognises the gateway bodies and not the RAG envelope", () => {
    expect(isGatewayUnauthorized({ error: "unauthorized" })).toBe(true);
    expect(isGatewayUnauthorized({ error: { code: "unauthenticated", message: "Missing" } })).toBe(false);
    expect(isAccessBlocked({ error: "blocked" })).toBe(true);
    expect(isAccessBlocked({ error: { code: "forbidden", message: "User is blocked" } })).toBe(true);
    expect(isAccessBlocked({ error: "unauthorized" })).toBe(false);
  });

  it("builds the login URL with the current address", () => {
    expect(loginUrl("https://rag.filenkov.store/files", "https://filenkov.store")).toBe(
      "https://filenkov.store/auth?return_to=https%3A%2F%2Frag.filenkov.store%2Ffiles",
    );
  });
});
