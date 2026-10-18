export function isGatewayUnauthorized(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  return (body as { error?: unknown }).error === "unauthorized";
}

export function isAccessBlocked(body: unknown): boolean {
  if (!body || typeof body !== "object") return false;
  const error = (body as { error?: unknown }).error;
  if (error === "blocked") return true;
  if (error && typeof error === "object" && (error as { code?: unknown }).code === "forbidden") {
    return true;
  }
  return false;
}

export function loginUrl(returnTo: string, publicOrigin?: string): string {
  const configured = (publicOrigin ?? import.meta.env.VITE_PUBLIC_ORIGIN ?? "").trim().replace(/\/$/, "");
  const origin = configured || (typeof window !== "undefined" ? window.location.origin : "http://localhost");
  const url = new URL("/auth", `${origin}/`);
  url.searchParams.set("return_to", returnTo);
  return url.toString();
}

export const navigation = {
  assign(url: string): void {
    window.location.assign(url);
  },
};

export function redirectToLogin(): void {
  navigation.assign(loginUrl(window.location.href));
}
