/**
 * API client for the div:ide portal/app.
 *
 * Auth: bearer-token in localStorage under `divide_token`. The token
 * is sent on every request as `X-Divide-Token` (matches the FastAPI
 * `current_token` dependency in services/api/app/core/auth.py).
 *
 * Errors: rejected fetch / non-2xx response -> throws ApiError so
 * React components can render the message and the toast helper can
 * pop a notification.
 */

const TOKEN_KEY = "divide_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function authHeaders(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const tok = getToken();
  if (tok) h.set("X-Divide-Token", tok);
  if (!h.has("Content-Type") && extra === undefined) {
    /* JSON body not yet supplied; let per-call decide */
  }
  return h;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = authHeaders(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    /* not JSON; leave as text */
  }
  if (!res.ok) {
    throw new ApiError(res.status, path, `HTTP ${res.status} ${path}`, parsed);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) =>
    request<T>(path, { method: "DELETE" }),
};

// ---------- credential login (F3-prep) --------------------------------------
//
// POST /api/v1/auth/login with username + password. On success the
// server returns an HMAC token (same shape as tools/issue_token.py
// emits) and we stash it in localStorage so subsequent calls work
// without a manual paste.
//
// The fetch goes through a stripped-down request helper (no
// X-Divide-Token header attached — there is none yet). On 401 the
// caller gets an ApiError with detail "invalid credentials"; on
// 429 the detail is "too many failed login attempts …".

export interface LoginResponse {
  token: string;
  sub: string;
  role: string;
  iat: number;
  exp: number;
  ttl_remaining_s: number;
}

export async function login(sub: string, password: string): Promise<LoginResponse> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sub, password }),
  });
  const text = await res.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    throw new ApiError(
      res.status,
      "/api/v1/auth/login",
      `HTTP ${res.status} /api/v1/auth/login`,
      parsed,
    );
  }
  return parsed as LoginResponse;
}

export async function logout(): Promise<void> {
  // Best-effort. The token in localStorage is the actual session;
  // the server logout is stateless today. We still POST so future
  // revocation lists get a chance to fire (no-op today).
  try {
    await fetch("/api/v1/auth/logout", { method: "POST" });
  } catch {
    /* swallow — local clear below is the real logout */
  }
  setToken("");
}
