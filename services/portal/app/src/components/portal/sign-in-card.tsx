/**
 * SignInCard — credential login (F3-prep / F-signin-ux / F-reset-ux).
 *
 * Renders username + password fields + a "Sign in" button. On
 * submit, POSTs to /api/v1/auth/login. On success, stashes the
 * returned HMAC token in localStorage and the parent re-renders
 * the authenticated layout. On failure, shows a banner with the
 * server's detail string.
 *
 * F-signin-ux: this card is now the DEFAULT landing page for
 * returning deployments (probe says needs_setup=false). The
 * optional `onNeedsSetup` callback lets a first-timer escape to
 * the OnboardingWizard by clicking "First time? Set up div:ide".
 *
 * F-reset-ux: the "Forgot password?" link swaps the card body
 * for ForgotPasswordCard. The user enters their username, hits
 * Notify admin, and is told to contact their admin for a reset
 * link. (No SMTP -- div:ide is LAN-only.)
 *
 * Replaces the old "paste your token" UX for non-SSH operators.
 * SSH operators can still paste a token directly into TokenBar;
 * TokenBar and SignInCard coexist — whichever has a token wins.
 *
 * 401 -> "Invalid username or password" (the server returns the
 * generic "invalid credentials" detail; we don't change it).
 * 429 -> "Too many failed attempts. Try again in N minutes."
 * 422 -> "Username and password are required."
 * other -> raw server message.
 */

import { useState } from "react";
import { LogIn, ShieldCheck, Wand2, HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, login, setToken } from "@/lib/api";
import { emitTokenChange } from "@/lib/auth";
import { ForgotPasswordCard } from "./forgot-password-card";

interface SignInCardProps {
  /** Called when the user clicks "First time? Set up div:ide →".
   *  Parent (app.tsx) swaps in the OnboardingWizard. */
  onNeedsSetup?: () => void;
  /** Called after a successful sign-in. The argument is the active
   *  hash view the operator was trying to reach (e.g. "operate"),
   *  or null if they came in cold. The parent uses it to switch
   *  tabs after auth state propagates. */
  onSignedIn?: (nextView: string | null) => void;
}

export function SignInCard({
  onNeedsSetup,
  onSignedIn,
}: SignInCardProps = {}) {
  const [mode, setMode] = useState<"signin" | "forgot">("signin");
  const [sub, setSub] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!sub.trim() || !password) {
      setError("Username and password are required.");
      return;
    }
    setSubmitting(true);
    try {
      const resp = await login(sub.trim(), password);
      setToken(resp.token);
      emitTokenChange(resp.token);
      setPassword(""); // best-effort: clear the password field
      // F-auth-ux (Plan A4): preserve the operator's intended
      // destination across the sign-in flow. If they came in via
      // #operate (e.g. from a stale email link), tell the parent so
      // it doesn't dump them on Dashboard.
      onSignedIn?.(_readNextViewFromHash());
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        if (e.status === 401) {
          setError("Invalid username or password.");
        } else if (e.status === 429) {
          setError(
            "Too many failed attempts. Try again in a few minutes.",
          );
        } else if (e.status === 422) {
          setError("Username and password are required.");
        } else {
          const detail = extractDetail(e.body) ?? `HTTP ${e.status}`;
          setError(detail);
        }
      } else {
        setError(
          e instanceof Error ? e.message : "Network error — try again.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm rounded-md border border-border bg-card p-6 shadow-sm">
      {mode === "forgot" ? (
        <ForgotPasswordCard onCancel={() => setMode("signin")} />
      ) : (
        <>
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold tracking-tight">
              Sign in to div:ide
            </h2>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">
            Enter your username and password to continue.
          </p>

          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="signin-sub"
                className="mb-1 block text-sm font-medium"
              >
                Username
              </label>
              <Input
                id="signin-sub"
                type="text"
                autoComplete="username"
                spellCheck={false}
                value={sub}
                onChange={(e) => setSub(e.target.value)}
                placeholder="alice"
                disabled={submitting}
                className="font-mono"
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
              />
            </div>
            <div>
              <label
                htmlFor="signin-password"
                className="mb-1 block text-sm font-medium"
              >
                Password
              </label>
              <Input
                id="signin-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={submitting}
              />
            </div>

            {error && (
              <div
                role="alert"
                data-testid="sign-in-error"
                className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={submitting}
              className="w-full"
            >
              <LogIn className="mr-2 h-4 w-4" />
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          {/* Forgot password + first-time-setup escape hatches */}
          <div className="mt-4 flex flex-col gap-2 border-t border-border pt-4">
            <button
              type="button"
              onClick={() => setMode("forgot")}
              data-testid="forgot-password-link"
              className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <HelpCircle className="h-3.5 w-3.5 shrink-0" />
              Forgot your password?
            </button>
            {onNeedsSetup && (
              <button
                type="button"
                onClick={onNeedsSetup}
                className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                <Wand2 className="h-3.5 w-3.5 shrink-0" />
                First time here? Set up div:ide →
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function extractDetail(body: unknown): string | null {
  if (
    body &&
    typeof body === "object" &&
    "detail" in body &&
    typeof (body as { detail: unknown }).detail === "string"
  ) {
    return (body as { detail: string }).detail;
  }
  return null;
}

/**
 * Read a `?next=<view>` query string OR a `#<view>` hash from the
 * current URL. Returns the view key if it matches a known portal
 * tab, else null. Used by F-auth-ux (Plan A4) to round-trip a deep
 * link through sign-out → sign-in.
 */
const KNOWN_VIEWS = new Set([
  "dashboard", "operate", "observe", "admin", "history", "profile",
]);

function _readNextViewFromHash(): string | null {
  if (typeof window === "undefined") return null;
  // Prefer ?next=… (preserved across sign-in round trips).
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  if (next && KNOWN_VIEWS.has(next)) return next;
  // Fall back to #… (current hash).
  const h = window.location.hash.replace(/^#\/?/, "");
  if (KNOWN_VIEWS.has(h)) return h;
  return null;
}
