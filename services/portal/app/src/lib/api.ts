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

/**
 * Extract the most informative error message from an `ApiError` (or any
 * thrown value).
 *
 * Resolution order:
 *   1. If the server returned a JSON body with a `detail` field, return
 *      that. `detail` may be:
 *        - a string (most endpoints — the standard FastAPI shape), or
 *        - an object with a `message` field (the structured `SdnPermissionError`
 *          response we surface when the PVE token is missing `SDN.Allocate`),
 *        - or any other JSON value (we `JSON.stringify` it as a last resort
 *          so the user at least sees something).
 *   2. Fall back to `HTTP <status> <url>` (mirrors the historical message).
 *   3. Fall back to the `Error.message` for non-`ApiError` throws.
 *   4. Final fallback: `"Network error"`.
 *
 * This helper was promoted from a local helper in `step0-pve-setup.tsx`
 * after the Q7 ProxmoxAPIError→502 fix made `body.detail` carry the
 * actionable PVE error text. Every portal error toast should now route
 * through this so the operator sees *why* a request failed, not just
 * the HTTP status.
 */
export function detailFromError(e: unknown): string {
  if (
    e &&
    typeof e === "object" &&
    "body" in e &&
    (e as { body?: { detail?: unknown } }).body &&
    (e as { body: { detail?: unknown } }).body.detail !== undefined
  ) {
    const d = (e as { body: { detail: unknown } }).body.detail;
    if (typeof d === "string") return d;
    if (typeof d === "object" && d && "message" in d) {
      return String((d as { message: unknown }).message);
    }
    try {
      return JSON.stringify(d);
    } catch {
      return String(d);
    }
  }
  if (
    e &&
    typeof e === "object" &&
    "status" in e &&
    "url" in e
  ) {
    const status = (e as { status: number }).status;
    const url = (e as { url: string }).url;
    return `HTTP ${status} ${url}`;
  }
  if (e instanceof Error) return e.message;
  return "Network error";
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

// ---------- setup probe (F-signin-ux) ---------------------------------------
//
// GET /api/v1/auth/setup → { needs_setup: bool }
// Public endpoint — no token required. Used by app.tsx on mount to decide
// whether to show the sign-in form (returning deployment, needs_setup=false)
// or the onboarding wizard (empty deployment, needs_setup=true).

export interface SetupProbeResponse {
  needs_setup: boolean;
}

export async function probeSetup(): Promise<SetupProbeResponse> {
  const res = await fetch("/api/v1/auth/setup");
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
      "/api/v1/auth/setup",
      `HTTP ${res.status} /api/v1/auth/setup`,
      parsed,
    );
  }
  return parsed as SetupProbeResponse;
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

// ---------- password reset (F-reset-ux) ------------------------------------
//
// Three endpoints backing the password-reset flow:
//   * POST /auth/forgot-password        -- public; always 202.
//   * POST /auth/reset-password         -- public; consumes the token.
//   * POST /auth/users/{sub}/issue-reset -- admin-only; mints a link.
//
// The portal wires these up like this:
//
//   SignInCard shows a "Forgot password?" link. Clicking it opens
//     the ForgotPasswordCard, which POSTs /forgot-password and
//     tells the user to contact their admin.
//   Admin clicks "Reset link" on a row in UserListCard. The response
//     contains a magic_link the admin copies and sends to the user
//     out-of-band (Slack / email / etc.).
//   The user clicks the link, lands on the portal with ?sub=&token=
//     in the hash, and the app.tsx router renders ResetPasswordCard.
//     They submit a new password; the card POSTs /reset-password,
//     on success lands on the sign-in form.
//
// The functions below are intentionally tiny — they're thin wrappers
// over the api.post() / fetch() helpers so the components don't have
// to know about endpoint paths or response shapes.

export async function requestPasswordReset(sub: string): Promise<void> {
  // 202 always; body is generic. We don't read it -- the UI shows a
  // canned "ask your admin" message.
  await api.post("/api/v1/auth/forgot-password", { sub });
}

export interface IssueResetLinkResponse {
  sub: string;
  reset_token: string;
  magic_link: string;
  expires_at: string;
}

export async function issuePasswordResetLink(
  sub: string,
): Promise<IssueResetLinkResponse> {
  return api.post<IssueResetLinkResponse>(
    `/api/v1/auth/users/${encodeURIComponent(sub)}/issue-reset`,
  );
}

export async function submitPasswordReset(
  sub: string,
  token: string,
  newPassword: string,
): Promise<void> {
  await api.post("/api/v1/auth/reset-password", {
    sub,
    token,
    new_password: newPassword,
  });
}

// ----------------------------------------------------------------------
// PVE runtime config (day-1 web setup; used by the onboarding wizard's
// PveCredentialsStep before Step0/Step1).
//
// These three helpers wrap the GET / POST / DELETE on
// /api/v1/admin/pve-config. The wizard's PveCredentialsStep calls
// ``getPveConfig`` on mount to discover whether the operator already
// configured PVE (in which case it auto-skips the form). If not, it
// calls ``postPveConfig`` with the form values; on success the wizard
// advances to Step0 (PVE bridges). ``deletePveConfig`` is exposed for
// the admin UI's "reset to env-vars" escape hatch -- not used by the
// wizard itself, but included here for consistency.
//
// Auth note (P11): these are admin-only endpoints, but Step -1
// runs BEFORE Step 1 (admin bootstrap), so the wizard's mount path
// has no admin token yet. The useEffect that calls getPveConfig
// catches the expected 401 (no auth header on first paint) and
// renders an empty form -- the operator submits, PveCredentialsStep
// posts, the wizard advances. Once Step 1 mints an admin token,
// subsequent wizard mounts (e.g. revisiting the wizard tab after
// a session rotation) auto-skip past Step -1 because the GET now
// succeeds. See OnboardingWizard for the step transitions.

export interface PveConfigPublic {
  source: "db" | "env";
  host: string | null;
  port: number;
  user: string;
  token_id: string | null;
  /** Always "***" -- the real secret is never returned from the API. */
  token_secret: string;
  verify_ssl: boolean;
  node: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export async function getPveConfig(): Promise<PveConfigPublic> {
  return api.get<PveConfigPublic>("/api/v1/admin/pve-config");
}

export interface PostPveConfigInput {
  host: string;
  port?: number;
  user: string;
  token_id: string;
  token_secret: string;
  verify_ssl?: boolean;
  node?: string | null;
}

export interface PostPveConfigResponse extends PveConfigPublic {
  probed: boolean;
  message: string;
}

export async function postPveConfig(
  body: PostPveConfigInput,
): Promise<PostPveConfigResponse> {
  return api.post<PostPveConfigResponse>(
    "/api/v1/admin/pve-config",
    body,
  );
}

export async function deletePveConfig(): Promise<{ deleted: boolean; message: string }> {
  return api.delete<{ deleted: boolean; message: string }>(
    "/api/v1/admin/pve-config",
  );
}

/**
 * Service-status snapshot for the Config tab's "Deployment status"
 * panel. Returns the same shape as the server: PVE reachability,
 * wg-easy probe, WireGuard env summary, disk usage, audit recency.
 *
 * Fails soft by design -- callers should treat any thrown error as
 * "service-status itself unavailable" rather than drilling in.
 */
export interface ServiceStatus {
  captured_at: string;
  pve: {
    reachable: boolean;
    version: string | null;
    error: string | null;
  };
  wg_easy: {
    state: "up" | "unreachable";
    target: string;
    error?: string;
  };
  wireguard: {
    wg_host: string | null;
    wg_default_dns: string | null;
    peer_secret_set: boolean;
    ready: boolean;
  };
  disk:
    | {
        path: string;
        total_gb: number;
        used_gb: number;
        free_gb: number;
        percent_used: number;
      }
    | { path: string; error: string };
  audit: {
    latest: string | null;
    state: "fresh" | "stale" | "empty" | "unknown";
    age_hours?: number;
  };
  all_ok: boolean;
}

export async function getServiceStatus(): Promise<ServiceStatus> {
  return api.get<ServiceStatus>("/api/v1/admin/service-status");
}
