/**
 * SignInCard — credential login (F3-prep / F-signin-ux).
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
import { LogIn, ShieldCheck, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, login, setToken } from "@/lib/api";
import { emitTokenChange } from "@/lib/auth";

interface SignInCardProps {
  /** Called when the user clicks "First time? Set up div:ide →".
   *  Parent (app.tsx) swaps in the OnboardingWizard. */
  onNeedsSetup?: () => void;
}

export function SignInCard({ onNeedsSetup }: SignInCardProps = {}) {
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
      // The parent re-renders because useMe() re-fetches on the
      // token-change event. No explicit callback needed.
      setPassword(""); // best-effort: clear the password field
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

      {/* First-time / empty-deployment escape hatch */}
      {onNeedsSetup && (
        <div className="mt-4 border-t border-border pt-4">
          <button
            type="button"
            onClick={onNeedsSetup}
            className="flex w-full items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <Wand2 className="h-3.5 w-3.5 shrink-0" />
            First time here? Set up div:ide →
          </button>
        </div>
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
