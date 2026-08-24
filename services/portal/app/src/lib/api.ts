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
};
