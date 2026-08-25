/**
 * ResetPasswordCard -- renders when the URL hash contains
 * ``?sub=<sub>&token=<token>`` (typically the user clicked a
 * magic link the admin sent).
 *
 * Three-step UX:
 *
 *   1. Initial render: form with two password fields + submit.
 *   2. On submit: POSTs /api/v1/auth/reset-password with the
 *      sub + token + new_password. The endpoint clears the
 *      token atomically with the password write.
 *   3. On 204: drop the hash params, hand off to the sign-in
 *      form via the parent's onReset callback. The parent
 *      (app.tsx) re-renders SignInCard automatically.
 *
 * Error modes:
 *   * 401 -- generic "invalid or expired reset token". This
 *      covers all four failure paths on the server side (no
 *      token, expired, mismatched, user gone).
 *   * 422 -- password too short / missing fields.
 *   * other -- raw server message.
 *
 * Why a separate component instead of inline in SignInCard:
 * the URL hash is the dispatch signal; keeping the reset card
 * independent makes the routing in app.tsx simpler and lets us
 * unit-test the form in isolation.
 */

import { useState } from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, submitPasswordReset } from "@/lib/api";

interface ResetPasswordCardProps {
  /** Subject whose password is being reset. */
  sub: string;
  /** One-time reset token from the URL hash. */
  token: string;
  /** Fired on a successful reset. The parent (app.tsx) clears
   *  the hash and re-renders the sign-in form. */
  onReset: () => void;
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

export function ResetPasswordCard({
  sub,
  token,
  onReset,
}: ResetPasswordCardProps) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await submitPasswordReset(sub, token, password);
      setPassword("");
      setConfirm("");
      onReset();
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        if (e.status === 401) {
          setError(
            "Invalid or expired reset link. Ask your admin to send a new one.",
          );
        } else if (e.status === 422) {
          setError("Password must be at least 8 characters.");
        } else {
          setError(extractDetail(e.body) ?? `HTTP ${e.status}`);
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
    <Card
      data-testid="reset-password-card"
      className="mx-auto w-full max-w-md"
    >
      <CardHeader>
        <CardTitle>
          <span className="inline-flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Reset your password
          </span>
        </CardTitle>
        <CardDescription>
          Set a new password for{" "}
          <span className="font-mono text-foreground">{sub}</span>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label
              htmlFor="reset-password"
              className="mb-1 block text-sm font-medium"
            >
              New password
            </label>
            <Input
              id="reset-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              disabled={submitting}
              data-testid="reset-password-input"
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
            />
          </div>
          <div>
            <label
              htmlFor="reset-password-confirm"
              className="mb-1 block text-sm font-medium"
            >
              Confirm new password
            </label>
            <Input
              id="reset-password-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="••••••••"
              disabled={submitting}
              data-testid="reset-password-confirm-input"
            />
          </div>
          {error && (
            <div
              role="alert"
              data-testid="reset-password-error"
              className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
            >
              {error}
            </div>
          )}
          <Button
            type="submit"
            disabled={submitting}
            className="w-full"
            data-testid="reset-password-submit"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <KeyRound className="mr-2 h-4 w-4" />
            )}
            {submitting ? "Resetting…" : "Set new password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}