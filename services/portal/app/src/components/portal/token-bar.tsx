import { useEffect, useState } from "react";
import { Eye, EyeOff, KeyRound, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, getToken, setToken } from "@/lib/api";

interface Me {
  /** Decoded token sub — "alice" or whatever the user typed. */
  sub: string;
  /** Role string from the token (free-form for L2). */
  role: string;
}

/**
 * Top-of-page sign-in bar.
 *
 * - Empty input -> "anonymous" placeholder; portal still works for
 *   public endpoints (e.g. /api/v1/scenarios is public).
 * - Non-empty input -> token saved to localStorage and forwarded on
 *   every subsequent fetch.
 * - Sign-out clears localStorage.
 *
 * "whoami" is a tiny inline decoder: the L2 token is a
 * base64url-encoded JSON payload signed with HMAC-SHA256. We only
 * trust the API to verify, but the *unverified* `sub`+`role` is
 * useful for the UI ("signed in as alice, role=red").
 */
export function TokenBar() {
  const [token, setLocalToken] = useState(getToken());
  const [reveal, setReveal] = useState(false);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (!token) {
      setMe(null);
      return;
    }
    const decoded = decodeUnverified(token);
    if (decoded) {
      setMe({ sub: decoded.sub, role: decoded.role });
    } else {
      setMe(null);
    }
    // Hit a known-authenticated endpoint to confirm the token works.
    // /api/v1/proxmox/health returns 200/401 — never throws.
    api
      .get<{ status?: string }>("/api/v1/proxmox/health")
      .then(() => setMe((prev) => prev ?? { sub: "?", role: "?" }))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) {
          setMe(null);
        }
      });
  }, [token]);

  function onTokenChange(v: string) {
    setLocalToken(v);
    setToken(v);
  }

  function onSignOut() {
    onTokenChange("");
    setMe(null);
  }

  return (
    <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-background/95 px-6 py-3 backdrop-blur">
      <KeyRound className="h-4 w-4 text-muted-foreground" />
      <span className="text-sm font-medium text-muted-foreground">Token:</span>
      <Input
        type={reveal ? "text" : "password"}
        autoComplete="off"
        spellCheck={false}
        placeholder="paste X-Divide-Token (divide issue-token …)"
        value={token}
        onChange={(e) => onTokenChange(e.target.value)}
        className="max-w-md font-mono text-xs"
      />
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setReveal((r) => !r)}
        aria-label={reveal ? "hide token" : "show token"}
      >
        {reveal ? (
          <EyeOff className="h-4 w-4" />
        ) : (
          <Eye className="h-4 w-4" />
        )}
      </Button>
      <div className="ml-auto flex items-center gap-3">
        {me ? (
          <>
            <span className="text-sm">
              <span className="text-muted-foreground">signed in as </span>
              <span className="font-semibold">{me.sub}</span>
              <span className="text-muted-foreground"> · {me.role}</span>
            </span>
            <Button variant="outline" size="sm" onClick={onSignOut}>
              <LogOut className="mr-1 h-3 w-3" /> Sign out
            </Button>
          </>
        ) : (
          <span className="text-sm italic text-muted-foreground">
            {token ? "checking…" : "anonymous"}
          </span>
        )}
      </div>
    </header>
  );
}

interface UnverifiedPayload {
  sub: string;
  role: string;
}

/** Best-effort decode of the unverified payload for UI purposes only.
 *  Returns null on any malformed input. The signature is verified
 *  server-side; the UI never trusts this for authorization. */
function decodeUnverified(token: string): UnverifiedPayload | null {
  try {
    const [payload] = token.split(".");
    if (!payload) return null;
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    const json = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    const obj = JSON.parse(json) as Partial<UnverifiedPayload>;
    if (typeof obj.sub !== "string" || typeof obj.role !== "string") {
      return null;
    }
    return { sub: obj.sub, role: obj.role };
  } catch {
    return null;
  }
}
