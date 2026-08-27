/**
 * UserListCard — admin view of every div:ide user.
 *
 * Backs onto `GET /api/v1/auth/users` (F3-prep) +
 * `POST /api/v1/auth/users/{sub}/toggle-disabled` (F9.4) +
 * `POST /api/v1/auth/users/{sub}/issue-reset` (F-reset-ux).
 * All three endpoints are admin-only; this card is therefore
 * only mounted for the admin role. If a non-admin somehow
 * renders it, the API calls fail 403 and the card shows an
 * error banner.
 *
 * Actions:
 *   * View: sub, role, disabled, last_login_at, created_at.
 *   * Toggle: click the disabled badge to flip it. Posts to
 *     `/api/v1/auth/users/{sub}/toggle-disabled`; the server
 *     returns the refreshed row and we patch it in place so
 *     the badge updates without a full reload.
 *   * Reset link: click to mint a one-time password-reset link
 *     for the user. The response includes a magic_link the admin
 *     copies to clipboard and sends to the locked-out user via
 *     whatever channel exists (Slack / email / carrier pigeon).
 *
 * F9.4 history: prior to F9.4 the toggle was a stub that
 * surfaced a 404-style "not wired up yet" message. The
 * endpoint + UI wiring landed together so the click now does
 * what the badge claims it does.
 */

import { useEffect, useState } from "react";
import { Loader2, Mail, RefreshCw, UserCog } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "./empty-state";
import { useToasts } from "./toast";
import {
  api,
  ApiError,
  detailFromError,
  issuePasswordResetLink,
  type IssueResetLinkResponse,
} from "@/lib/api";

export interface UserRow {
  sub: string;
  role: string;
  disabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export function UserListCard() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [togglePending, setTogglePending] = useState<string | null>(null);
  const [resetPending, setResetPending] = useState<string | null>(null);
  const toasts = useToasts();

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<UserRow[]>("/api/v1/auth/users");
      setUsers(data);
    } catch (e: unknown) {
      setError(detailFromError(e));
      setUsers([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onToggle(sub: string) {
    // F9.4: the toggle endpoint exists now (POST /auth/users/
    // {sub}/toggle-disabled, admin-only). On success the
    // server returns the refreshed user row; we replace the
    // local copy so the badge updates without a full reload.
    setTogglePending(sub);
    try {
      const updated = await api.post<UserRow>(
        `/api/v1/auth/users/${sub}/toggle-disabled`,
      );
      setUsers((prev) => prev.map((u) => (u.sub === sub ? updated : u)));
    } catch (e: unknown) {
      const status = e instanceof ApiError ? e.status : 0;
      setError(
        status === 404
          ? `User "${sub}" not found (deleted between list + click?).`
          : status === 403
          ? `You need admin to toggle "${sub}".`
          : `toggle failed: HTTP ${status || "unknown"}`,
      );
    } finally {
      setTogglePending(null);
    }
  }

  // F-reset-ux: mint a reset link for a user and copy the magic
  // URL to clipboard. The admin pastes it into Slack / email /
  // whatever channel they have. We surface the link as a toast
  // so the admin can confirm the copy happened, and log the raw
  // token to the console for headless debugging.
  async function copyToClipboard(text: string): Promise<boolean> {
    try {
      if (
        typeof navigator !== "undefined" &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === "function"
      ) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      // fall through to the legacy prompt
    }
    return false;
  }

  async function onIssueReset(sub: string) {
    setResetPending(sub);
    setError(null);
    try {
      const resp: IssueResetLinkResponse = await issuePasswordResetLink(sub);
      const copied = await copyToClipboard(resp.magic_link);
      if (copied) {
        toasts.success(
          `Reset link copied to clipboard for "${sub}". Paste it into Slack / email.`,
        );
      } else {
        // Clipboard API not available (older browser / non-https).
        // Show the link in a way the admin can still grab it.
        toasts.info(
          `Reset link for "${sub}": ${resp.magic_link} (expires ${resp.expires_at})`,
          15_000,
        );
      }
      // eslint-disable-next-line no-console
      console.info(
        `[F-reset-ux] minted reset link for ${sub}: ${resp.magic_link} (token=${resp.reset_token}, expires=${resp.expires_at})`,
      );
    } catch (e: unknown) {
      const status = e instanceof ApiError ? e.status : 0;
      const detail =
        e instanceof ApiError && e.body && typeof e.body === "object"
          ? (e.body as { detail?: string }).detail
          : undefined;
      const msg =
        status === 404
          ? `User "${sub}" not found.`
          : status === 403
          ? `You need admin to issue a reset link for "${sub}".`
          : detail || `HTTP ${status || "unknown"}`;
      setError(msg);
      toasts.error(msg);
    } finally {
      setResetPending(null);
    }
  }

  return (
    <Card data-testid="user-list-card">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <UserCog className="h-4 w-4 text-muted-foreground" />
              Users
            </span>
          </CardTitle>
          <CardDescription>
            {users.length === 0
              ? "No users have signed in yet."
              : `${users.length} user${users.length === 1 ? "" : "s"} — click the badge to enable / disable an account.`}
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={load}
          aria-label="Refresh users"
          disabled={loading}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </CardHeader>
      <CardContent>
        {error && (
          <div
            role="alert"
            data-testid="user-list-error"
            className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
          >
            {error}
          </div>
        )}
        {!error && loading && (
          <p className="text-sm italic text-muted-foreground">Loading…</p>
        )}
        {!error && !loading && users.length === 0 && (
          <EmptyState
            title="No users yet"
            description="Set DIVIDE_BOOTSTRAP_ADMIN_SUB + DIVIDE_BOOTSTRAP_ADMIN_PASSWORD on the API container to create the first admin. See docs/USERS.md."
          />
        )}
        {!error && !loading && users.length > 0 && (
          <ul className="divide-y divide-border" data-testid="user-list">
            {users.map((u) => (
              <li
                key={u.sub}
                className="flex items-center gap-3 px-3 py-2 text-sm"
                data-testid="user-list-row"
                data-sub={u.sub}
                data-role={u.role}
              >
                <span className="font-mono text-xs">{u.sub}</span>
                <span className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs text-secondary-foreground">
                  {u.role}
                </span>
                {u.disabled ? (
                  <span
                    data-testid="user-disabled-badge"
                    className="rounded bg-red-900/60 px-1.5 py-0.5 text-xs text-red-200"
                  >
                    disabled
                  </span>
                ) : (
                  <span className="rounded bg-emerald-900/50 px-1.5 py-0.5 text-xs text-emerald-200">
                    active
                  </span>
                )}
                <span className="ml-auto text-xs text-muted-foreground">
                  last seen{" "}
                  {u.last_login_at
                    ? new Date(u.last_login_at).toLocaleString()
                    : "never"}
                </span>
                {/* F-reset-ux: mint a one-time reset link for the
                    user. The admin copies it to clipboard and
                    sends it out-of-band. */}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={resetPending === u.sub}
                  onClick={() => onIssueReset(u.sub)}
                  data-testid="user-issue-reset"
                  title="Generate a one-time password-reset link"
                >
                  {resetPending === u.sub ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Mail className="h-3 w-3" />
                  )}
                  <span className="ml-1.5">Reset link</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={togglePending === u.sub}
                  onClick={() => onToggle(u.sub)}
                  data-testid="user-toggle-disabled"
                >
                  {togglePending === u.sub
                    ? "…"
                    : u.disabled
                      ? "Enable"
                      : "Disable"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
