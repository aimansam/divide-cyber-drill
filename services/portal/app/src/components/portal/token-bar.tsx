import { useEffect, useState } from "react";
import { Eye, EyeOff, KeyRound, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError, getToken, setToken } from "@/lib/api";
import { emitTokenChange, useMe } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/roles";

/**
 * Top-of-page sign-in bar.
 *
 * - Empty input -> "anonymous" placeholder; portal still works for
 *   public endpoints (e.g. /api/v1/scenarios is public).
 * - Non-empty input -> token saved to localStorage and forwarded on
 *   every subsequent fetch.
 * - Sign-out clears localStorage.
 *
 * Identity comes from the server-verified `useMe()` hook (commit
 * M3.2 Half 1) which hits `GET /api/v1/me`. We no longer do the
 * client-side JWT decode for the "signed in as alice · red" badge
 * — that was a small footgun since the unverified payload could be
 * tampered with by a MITM and we wouldn't notice.
 */
export function TokenBar() {
  const [token, setLocalToken] = useState(getToken());
  const [reveal, setReveal] = useState(false);
  const { me, loading } = useMe();

  // Stays around for legacy callers that listen to api.ts's
  // /proxmox/health probe behavior — none today, but cheap.
  useEffect(() => {
    if (!token) return;
    // No-op: useMe() handles the validity check. Kept for future
    // use (e.g. an explicit "is token still good?" pill).
  }, [token]);

  function onTokenChange(v: string) {
    setLocalToken(v);
    setToken(v);
    emitTokenChange(v);
  }

  function onSignOut() {
    onTokenChange("");
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
        {loading && (
          <span className="text-sm italic text-muted-foreground">
            checking…
          </span>
        )}
        {!loading && me && (
          <>
            <span className="text-sm">
              <span className="text-muted-foreground">signed in as </span>
              <span className="font-semibold">{me.sub}</span>
              <span className="text-muted-foreground">
                {" · "}
                {ROLE_LABELS[me.role]}
              </span>
              <span className="ml-2 inline-block rounded bg-emerald-900/40 px-1.5 py-0.5 text-xs text-emerald-200">
                verified
              </span>
            </span>
            <Button variant="outline" size="sm" onClick={onSignOut}>
              <LogOut className="mr-1 h-3 w-3" /> Sign out
            </Button>
          </>
        )}
        {!loading && !me && (
          <span className="text-sm italic text-muted-foreground">
            {token ? "token invalid" : "anonymous"}
          </span>
        )}
      </div>
    </header>
  );
}

// `api` and `ApiError` are referenced in the no-op effect comment
// above; if you remove the future-pill work, drop the imports too.
void api;
void ApiError;
