/**
 * useMe() — single source of truth for the verified identity in the
 * React tree.
 *
 * Fetches `GET /api/v1/me` (a server-verified echo of the bearer
 * token's payload), caches the result per `sub`, and revalidates
 * whenever the local token changes.
 *
 * Why server-verified, not client-side decode:
 *
 *   - The portal used to base64-decode the JWT payload in
 *     `TokenBar` and trust it for display. That's a small footgun:
 *     an attacker who can MITM the browser can show a different
 *     identity without breaking the signature.
 *   - The server has the verified answer on hand; we just expose it
 *     (see services/api/app/routers/me.py).
 *
 * Token lifecycle:
 *
 *   - On mount: if there's a token in localStorage, hit /me.
 *   - On 401 (no token / invalid token): clear localStorage, me -> null.
 *   - On network error or 5xx: keep token, return error; the caller
 *     can choose to surface this. We don't auto-clear on transient
 *     failures — the user might just have a flaky connection.
 *   - On token change (via `setToken()`): re-fetch.
 *
 * Caching: keyed by `sub` so flipping tokens doesn't lose state
 * within a session. The cache lives on the React tree, not in
 * localStorage — refresh and you re-fetch.
 */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, getToken, setToken } from "@/lib/api";
import { isRole, type Role } from "@/lib/roles";

export interface Me {
  /** Decoded + verified subject ("alice", "admin-test", etc.). */
  sub: string;
  /** Verified role. */
  role: Role;
  /** Issued-at (unix seconds). */
  iat: number;
  /** Expires-at (unix seconds). */
  exp: number;
  /** Convenience: how many seconds are left before expiry. */
  ttl_remaining_s: number;
}

export interface UseMeState {
  me: Me | null;
  /** True while the initial /me request is in flight. */
  loading: boolean;
  /** Last network/parse error; cleared on success. */
  error: string | null;
  /** Force a re-fetch (e.g. after the user clicks Refresh). */
  refresh: () => void;
}

interface RawMe {
  sub?: unknown;
  role?: unknown;
  iat?: unknown;
  exp?: unknown;
  ttl_remaining_s?: unknown;
}

function parseMe(raw: RawMe): Me | null {
  if (
    typeof raw.sub !== "string" ||
    !isRole(raw.role) ||
    typeof raw.iat !== "number" ||
    typeof raw.exp !== "number" ||
    typeof raw.ttl_remaining_s !== "number"
  ) {
    return null;
  }
  return {
    sub: raw.sub,
    role: raw.role,
    iat: raw.iat,
    exp: raw.exp,
    ttl_remaining_s: raw.ttl_remaining_s,
  };
}

export function useMe(): UseMeState {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Bumping this counter forces a re-fetch even if the token
  // string didn't change.
  const [rev, setRev] = useState(0);

  // Keep a copy of the current token so the effect re-runs when it
  // changes. We track a separate "version" string so unrelated
  // localStorage writes don't trigger re-renders.
  const [tokenVersion, setTokenVersion] = useState(() => getToken());

  // Listen for cross-tab storage events so two open tabs stay in
  // sync without needing a real-time channel. Same-tab writes
  // (TokenBar onChange) call emitTokenChange() below; we
  // subscribe to that here too so same-tab and cross-tab are
  // handled in one place.
  useEffect(() => {
    function onExternalChange() {
      setTokenVersion(getToken());
    }
    window.addEventListener("storage", onExternalChange);
    const unsubscribe = subscribeTokenChange(onExternalChange);
    return () => {
      window.removeEventListener("storage", onExternalChange);
      unsubscribe();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchMe() {
      const tok = getToken();
      if (!tok) {
        setMe(null);
        setError(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const raw = await api.get<RawMe>("/api/v1/me");
        const parsed = parseMe(raw);
        if (cancelled) return;
        if (parsed === null) {
          // Server returned a payload we don't understand. Treat
          // it as "unknown identity" — same UX as anon.
          setMe(null);
          setError("server returned an unexpected /api/v1/me payload");
        } else {
          setMe(parsed);
          setError(null);
        }
      } catch (e: unknown) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          // The token in localStorage is no longer valid. Clear it
          // so we don't loop on /me forever, then render anon.
          // F-auth-ux (Plan A2): also emit a sessionExpired event
          // so the app can show a toast and direct the operator to
          // the sign-in form rather than silently dropping them.
          setToken("");
          setMe(null);
          setError(null);
          emitSessionExpired();
        } else {
          const msg = e instanceof Error ? e.message : String(e);
          setMe(null);
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchMe();
    return () => {
      cancelled = true;
    };
  }, [tokenVersion, rev]);

  const refresh = useCallback(() => setRev((r) => r + 1), []);

  return { me, loading, error, refresh };
}

/**
 * Programmatic "I just changed the token" hook for TokenBar.
 * TokenBar calls `emitTokenChange(v)` after writing localStorage
 * so any mounted useMe() re-fetches /me.
 *
 * We export this as a tiny module-level event so components don't
 * have to plumb a callback through props. (A useSyncExternalStore
 * would be the cleaner modern API but this is small and works.)
 */
let versionListeners = new Set<(v: string) => void>();

export function emitTokenChange(token: string): void {
  for (const fn of versionListeners) fn(token);
}

export function subscribeTokenChange(fn: (v: string) => void): () => void {
  versionListeners.add(fn);
  return () => {
    versionListeners.delete(fn);
  };
}

/**
 * sessionExpired — fired once when a previously-valid token returns 401
 * from /api/v1/me. Components (ToastHost, app.tsx) listen for this to
 * show a one-shot "your session expired" toast instead of silently
 * dropping the operator back to the sign-in page.
 *
 * Fire-and-forget; listeners may register/unregister freely.
 */
let sessionExpiredListeners = new Set<() => void>();

export function emitSessionExpired(): void {
  for (const fn of sessionExpiredListeners) fn();
}

export function subscribeSessionExpired(fn: () => void): () => void {
  sessionExpiredListeners.add(fn);
  return () => {
    sessionExpiredListeners.delete(fn);
  };
}

/**
 * Helper: format seconds-until-expiry as "4h 12m" / "15m" / "expired".
 * Used by TopNav to surface the session-expiry pill.
 */
export function formatTtl(seconds: number): string {
  if (seconds <= 0) return "expired";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}