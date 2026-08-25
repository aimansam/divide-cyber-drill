/**
 * ForgotPasswordCard -- "I forgot my password" flow.
 *
 * Renders a single sub field + submit button. On submit:
 *   * POSTs /api/v1/auth/forgot-password (always returns 202).
 *   * Swaps the form for a "we've notified your admin" message.
 *
 * The endpoint itself does NOT send anything (no SMTP). The
 * admin endpoint /auth/users/{sub}/issue-reset is what surfaces
 * the actual magic link; the admin pastes it into Slack / email.
 *
 * Why a "notify the admin" message instead of an "email sent":
 * div:ide runs on LAN with no SMTP. Telling the user "we sent
 * you an email" would be a lie. The honest version is "ask your
 * admin to send you a reset link" -- which is exactly what the
 * admin endpoint exists for.
 */

import { useState } from "react";
import { Check, Loader2, Send } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, requestPasswordReset } from "@/lib/api";

interface ForgotPasswordCardProps {
  /** Cancel returns to the sign-in form. */
  onCancel: () => void;
}

export function ForgotPasswordCard({ onCancel }: ForgotPasswordCardProps) {
  const [sub, setSub] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!sub.trim()) {
      setError("Username is required.");
      return;
    }
    setSubmitting(true);
    try {
      await requestPasswordReset(sub.trim());
      setSubmitted(true);
    } catch (e: unknown) {
      // 422 (validation) is the only meaningful error here; 202 is
      // the success path; 5xx is "the API is down, try again".
      if (e instanceof ApiError) {
        if (e.status === 422) {
          setError("Username is required.");
        } else {
          setError(`HTTP ${e.status}`);
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
      data-testid="forgot-password-card"
      className="mx-auto w-full max-w-md"
    >
      <CardHeader>
        <CardTitle>
          <span className="inline-flex items-center gap-2">
            <Send className="h-4 w-4 text-muted-foreground" />
            Forgot your password?
          </span>
        </CardTitle>
        <CardDescription>
          Enter your username. An admin will send you a reset link.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {submitted ? (
          <div
            data-testid="forgot-password-submitted"
            className="space-y-3"
          >
            <div className="flex items-start gap-2 rounded-md border border-emerald-700 bg-emerald-950/30 p-3 text-sm text-emerald-200">
              <Check className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                If{" "}
                <span className="font-mono">{sub.trim()}</span>{" "}
                exists, a reset link has been sent to your admin.
                Ask them to check the Admin tab and forward the
                link to you.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={onCancel}
              data-testid="forgot-password-back"
            >
              Back to sign in
            </Button>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="forgot-sub"
                className="mb-1 block text-sm font-medium"
              >
                Username
              </label>
              <Input
                id="forgot-sub"
                type="text"
                autoComplete="username"
                spellCheck={false}
                value={sub}
                onChange={(e) => setSub(e.target.value)}
                placeholder="alice"
                disabled={submitting}
                className="font-mono"
                data-testid="forgot-password-sub"
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
              />
            </div>
            {error && (
              <div
                role="alert"
                data-testid="forgot-password-error"
                className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
              >
                {error}
              </div>
            )}
            <div className="flex gap-2">
              <Button
                type="submit"
                disabled={submitting}
                className="flex-1"
                data-testid="forgot-password-submit"
              >
                {submitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Send className="mr-2 h-4 w-4" />
                )}
                {submitting ? "Notifying admin…" : "Notify admin"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onCancel}
                disabled={submitting}
                data-testid="forgot-password-cancel"
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}