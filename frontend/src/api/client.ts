import { isAccessBlocked, isGatewayUnauthorized, redirectToLogin } from "../shared/auth";
import { useSessionStore } from "../stores/sessionStore";

const FORBIDDEN_HEADERS = new Set([
  "authorization",
  "x-user-id",
  "x-auth-user-id",
  "x-auth-email",
  "x-auth-name",
  "x-auth-role",
]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | undefined;

  constructor(status: number, code: string, details?: Record<string, unknown>) {
    super(code || String(status));
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class AccessBlockedError extends Error {
  constructor() {
    super("blocked");
    this.name = "AccessBlockedError";
  }
}

export class AuthRedirectError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "AuthRedirectError";
  }
}

export class PreviewUnavailableError extends Error {
  constructor() {
    super("preview-unavailable");
    this.name = "PreviewUnavailableError";
  }
}

export class StreamBrokenError extends Error {
  constructor() {
    super("stream-broken");
    this.name = "StreamBrokenError";
  }
}

export function sanitizeHeaders(headers: Headers): Headers {
  const next = new Headers(headers);
  for (const name of [...next.keys()]) {
    const lower = name.toLowerCase();
    if (FORBIDDEN_HEADERS.has(lower) || lower.startsWith("x-auth-")) {
      next.delete(name);
    }
  }
  return next;
}

export function parseApiErrorBody(
  body: unknown,
): { code: string; message: string; details?: Record<string, unknown> } | null {
  if (!body || typeof body !== "object") return null;
  const error = (body as { error?: unknown }).error;
  if (!error || typeof error !== "object") return null;
  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string") return null;
  const message = (error as { message?: unknown }).message;
  const details = (error as { details?: unknown }).details;
  return {
    code,
    message: typeof message === "string" ? message : "",
    details: details && typeof details === "object" && !Array.isArray(details) ? (details as Record<string, unknown>) : undefined,
  };
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = sanitizeHeaders(new Headers(init.headers));
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 401 || response.status === 403) {
    const body: unknown = await response.clone().json().catch(() => null);
    if (response.status === 401 && isGatewayUnauthorized(body)) {
      redirectToLogin();
      throw new AuthRedirectError();
    }
    if (response.status === 403 && isAccessBlocked(body)) {
      useSessionStore.getState().block();
      throw new AccessBlockedError();
    }
  }
  return response;
}

export async function responseError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null);
  const parsed = parseApiErrorBody(body);
  return new ApiError(response.status, parsed?.code ?? "", parsed?.details);
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await apiFetch(path, { ...init, headers });
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
