/**
 * RunLifecycleCard — start a drill, watch it tick, cancel or stop it.
 *
 * Four actions, gated by role:
 *
 *   * Start:   POST /api/v1/drills  { scenario_id }
 *              Allowed: admin, lead, red
 *   * Refresh: GET  /api/v1/drills/{id}     (polls every 2s when live)
 *   * Cancel:  POST /api/v1/drills/{id}/cancel  { reason }
 *              Allowed: admin, lead, red
 *              Red may only cancel runs they started (server enforced
 *              by commit 4d840f9 — we mirror the rule client-side so
 *              the button is disabled instead of 403-ing on click).
 *   * Stop:    POST /api/v1/drills/{id}/stop   (Q17: admin/lead only)
 *              Operator-initiated force-stop. Differs from Cancel in
 *              that the audit row records ``run.stopped`` (not
 *              ``run.cancelled``) and the actor is the operator's
 *              token subject. Q19 adds the inline Stop button here
 *              so operators don't have to switch to the Admin tab.
 *
 * Roles (M3.2, Half 1): shown to admin, lead, red. Blue and observer
 * don't get this card at all (COMPOSITIONS table in app.tsx). The
 * server-side gate means an anon can't POST /drills either.
 *
 * Polling: a single useEffect owns a 2s interval while a run is
 * active. On unmount or status transition to a terminal state the
 * interval clears itself. ``stopped`` is now in TERMINAL_STATUSES
 * (Q18) so a stopped run does not keep polling.
 *
 * Asset preview: we render the vmid + IP for each asset once the
 * run reaches `provisioning`. The full AssetsCard lands in Half 2.
 */

import { useEffect, useRef, useState } from "react";
import {
  BookMarked,
  Download,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Settings,
  Shield,
  Square,
  CircleStop,
  AlertTriangle,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, detailFromError } from "@/lib/api";
import { hasRole, type Role } from "@/lib/roles";
import type { Scenario } from "@/components/portal/scenarios-card";

/**
 * Shape of a structured error response from the API.
 *
 * Q15: drill-start failures used to all surface the same banner
 * ("Open the Config tab to inspect PVE credentials and bridges")
 * regardless of the actual error. Now the API returns a JSON
 * ``detail`` object on rate-limit and other known errors with a
 * ``kind`` discriminator; the UI dispatches on it. If the
 * response detail is a plain string (older / un-tagged endpoints)
 * the kind falls back to ``"generic"`` and the banner keeps its
 * previous behaviour.
 */
interface DrillsErrorDetail {
  kind?: string;
  message?: string;
  subject?: string;
  count?: number;
  limit?: number;
  window_s?: number;
}

function parseErrorKind(rawBody: unknown): DrillsErrorDetail {
  if (
    rawBody &&
    typeof rawBody === "object" &&
    "body" in (rawBody as Record<string, unknown>)
  ) {
    const body = (rawBody as { body?: unknown }).body;
    if (body && typeof body === "object" && "detail" in (body as Record<string, unknown>)) {
      const detail = (body as { detail?: unknown }).detail;
      if (detail && typeof detail === "object") {
        return detail as DrillsErrorDetail;
      }
    }
  }
  return {};
}

const CAN_START: readonly Role[] = ["admin", "lead", "red"];
const CAN_CANCEL: readonly Role[] = ["admin", "lead", "red"];
// Q19: operator-initiated force-stop. Unlike Cancel (which a red
// trainee can call on their own run), Stop is restricted to roles
// with range-operator authority. Red team should not be able to
// kill drills other operators are running.
const CAN_STOP: readonly Role[] = ["admin", "lead"];
// Q23: Restart re-runs the same scenario with a fresh run_id.
// Anyone who can start a drill can restart one.
const CAN_RESTART: readonly Role[] = ["admin", "lead", "red"];
// Save-as-template is admin-only on the API side. Lead can
// stop/cancel but can't author templates.
const CAN_SAVE_AS_TEMPLATE: readonly Role[] = ["admin"];

const TERMINAL_STATUSES = new Set([
  "completed",
  "cancelled",
  "canceled",
  "stopped",
  "failed",
  "timeout",
]);

export interface RunAsset {
  asset_id?: number;
  role?: string;
  kind?: string;
  template?: string;
  status?: string;
  pve_vmid?: number | null;
  pve_node?: string | null;
  pve_ip?: string | null;
  error?: string | null;
}

export interface RunDetail {
  run_id: number;
  scenario_id?: number;
  // F9.1: exercise_id is null for legacy single-team Runs and
  // populated for F6 multi-team exercise Runs. The DrillConsole
  // uses this to decide whether to render the leaderboard +
  // live SOC stream inline.
  exercise_id?: number | null;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
  error?: string | null;
  assets?: RunAsset[];
}

interface RunLifecycleCardProps {
  meSub: string;
  meRole: Role;
  scenario: Scenario | null;
  pickedRunId: number | null;
  /**
   * Optional: navigate to the Config tab. Used by the drill-launch
   * error banner so the operator can fix PVE creds / bridges with
   * one click. Not all consumers wire it.
   */
  onNavigateToConfig?: () => void;
}
export function RunLifecycleCard({
  meSub,
  meRole,
  scenario,
  pickedRunId,
  onNavigateToConfig,
}: RunLifecycleCardProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * Q15: discriminate between drill-start error kinds so the
   * banner can show the right remediation.
   *   ``"rate_limited"`` -> "wait for window to reset" message
   *   ``"generic"``      -> "Open Config" banner (legacy behaviour)
   *   ``null``           -> no error to show
   */
  const [errorKind, setErrorKind] = useState<"rate_limited" | "generic" | null>(
    null,
  );
  const [cancelReason, setCancelReason] = useState("user requested");
  // Q23-#5: Save-as-template flow uses two extra local state
  // slots for the in-flight spinner + a 5s "saved!" toast so the
  // operator gets visual confirmation that the new template
  // row exists. Kept at the top with the other useStates so
  // hook ordering is stable.
  const [savingAsTemplate, setSavingAsTemplate] = useState(false);
  const [savedTemplateName, setSavedTemplateName] = useState<string | null>(
    null,
  );
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const canStart = hasRole(meRole, CAN_START);
  const canCancel = hasRole(meRole, CAN_CANCEL);
  // Q19: stop is operator-only. No "own-only" filter needed since
  // red doesn't have the role at all.
  const canStop = hasRole(meRole, CAN_STOP);
  // red can cancel any of *their* runs; admin/lead cancel anything.
  // This mirrors the server rule from commit 4d840f9.
  const canCancelThis =
    canCancel &&
    run !== null &&
    (meRole !== "red" || run.started_by === meSub);
  // Q23-#2 + #5: restart + save-as-template gates. Restart
  // re-uses POST /drills so it shares Start's role list;
  // save-as-template is admin-only on the API side.
  const canRestart = hasRole(meRole, CAN_RESTART);
  const canSaveAsTemplate = hasRole(meRole, CAN_SAVE_AS_TEMPLATE);

  function clearPoll() {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function fetchRun(id: number): Promise<RunDetail | null> {
    try {
      const data = await api.get<RunDetail>(`/api/v1/drills/${id}`);
      setRun(data);
      return data;
    } catch (e: unknown) {
      setError(detailFromError(e));
      return null;
    }
  }

  function startPoll(id: number) {
    clearPoll();
    pollRef.current = setInterval(() => {
      void fetchRun(id).then((r) => {
        if (r && TERMINAL_STATUSES.has(r.status)) {
          clearPoll();
        }
      });
    }, 2000);
  }

  useEffect(() => {
    if (pickedRunId === null) {
      setRun(null);
      clearPoll();
      return;
    }
    setLoading(true);
    fetchRun(pickedRunId)
      .then((r) => {
        if (r && !TERMINAL_STATUSES.has(r.status)) {
          startPoll(r.run_id);
        }
      })
      .finally(() => setLoading(false));
    return clearPoll;
  }, [pickedRunId]);

  async function onStart() {
    if (scenario === null) return;
    setError(null);
    setErrorKind(null);
    setLoading(true);
    try {
      const created = await api.post<RunDetail>("/api/v1/drills", {
        scenario_id: scenario.id,
      });
      setRun(created);
      if (!TERMINAL_STATUSES.has(created.status)) {
        startPoll(created.run_id);
      }
    } catch (e: unknown) {
      // Q15: distinguish rate-limit errors from PVE/bridge
      // errors. The rate-limit toast used to say
      // "Open the Config tab" which sent the operator to
      // the wrong place -- now we surface a different banner
      // (no Open-Config button; instead a "wait or check
      // service-status" message with the reset window).
      const structured = parseErrorKind(e);
      if (structured.kind === "rate_limited") {
        setErrorKind("rate_limited");
        setError(
          structured.message ?? detailFromError(e),
        );
      } else {
        setErrorKind("generic");
        setError(
          `${detailFromError(e)}\n\n→ Open the Config tab to inspect PVE credentials and bridges.`,
        );
      }
    } finally {
      setLoading(false);
    }
  }

  async function onCancel() {
    if (run === null || !canCancelThis) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await api.post<RunDetail>(
        `/api/v1/drills/${run.run_id}/cancel`,
        { reason: cancelReason, actor: meSub },
      );
      setRun(updated);
      clearPoll();
    } catch (e: unknown) {
      setError(detailFromError(e));
    } finally {
      setLoading(false);
    }
  }

  /**
   * Q23-#2: Restart = start a new drill with the same scenario.
   *
   * Useful for retakes. The new drill gets a fresh run_id, fresh
   * VM clones, fresh audit timeline. The previous run is left
   * alone (it's terminal; visible in History).
   *
   * RBAC: same as Start (admin / lead / red). The server doesn't
   * have a dedicated /restart endpoint; this re-uses POST /drills
   * with the scenario_id of the just-finished run. We could call
   * the explicit /drills/{id}/restart endpoint if/when one ships.
   */
  async function onRestart() {
    if (run === null || scenario === null) return;
    setLoading(true);
    setError(null);
    setErrorKind(null);
    try {
      const created = await api.post<RunDetail>("/api/v1/drills", {
        scenario_id: run.scenario_id ?? scenario.id,
      });
      setRun(created);
      if (!TERMINAL_STATUSES.has(created.status)) {
        startPoll(created.run_id);
      }
    } catch (e: unknown) {
      const structured = parseErrorKind(e);
      setErrorKind(
        structured.kind === "rate_limited" ? "rate_limited" : "generic",
      );
      setError(structured.message ?? detailFromError(e));
    } finally {
      setLoading(false);
    }
  }

  /**
   * Q23-#5: Save the just-finished run as a reusable template.
   *
   * The endpoint (POST /drills/{id}/save-as-template) supports
   * both live and terminal runs -- the operator's "bookmark"
   * button while a drill is still running. The current run row
   * is unchanged; a new template is created and bound.
   *
   * RBAC: admin-only on the API side.
   */
  async function onSaveAsTemplate() {
    if (run === null) return;
    const name = window.prompt(
      "Template name (used as the file-safe identifier):",
      `tpl-from-run-${run.run_id}`,
    );
    if (name === null) return;
    const title = window.prompt(
      "Template title (shown in the template picker):",
      `Captured from run #${run.run_id}`,
    );
    if (title === null) return;
    setSavingAsTemplate(true);
    setError(null);
    try {
      const out = await api.post<{ template_id?: number; id?: number }>(
        `/api/v1/drills/${run.run_id}/save-as-template`,
        { name, title },
      );
      setSavedTemplateName(name);
      // Keep the confirmation visible until the next interaction.
      setTimeout(() => setSavedTemplateName(null), 5000);
      console.log("[Q23] template saved", out);
    } catch (e: unknown) {
      setError(detailFromError(e));
    } finally {
      setSavingAsTemplate(false);
    }
  }

  /**
   * Q19: operator-initiated force-stop. Hits POST /drills/{id}/stop
   * which the API distinguishes from /cancel by writing a
   * ``run.stopped`` audit row (not ``run.cancelled``) and threading
   * the actor (token sub) into the audit record. No reason input --
   * stops are operational, not user-attributed.
   *
   * Optimistic UI: we set the run to ``"stopped"`` immediately so
   * the operator gets instant feedback, then reconcile with the
   * server response. If the server disagrees (e.g. 409 already-
   * terminal), we revert and re-fetch.
   */
  async function onStop() {
    if (run === null || !canStop || !hasLiveRun) return;
    setLoading(true);
    setError(null);
    // Optimistic state.
    const prevRun = run;
    setRun({ ...run, status: "stopped", ended_at: new Date().toISOString() });
    clearPoll();
    try {
      const updated = await api.post<RunDetail>(
        `/api/v1/drills/${run.run_id}/stop`,
      );
      setRun(updated);
    } catch (e: unknown) {
      // Revert and surface the error.
      setRun(prevRun);
      setError(detailFromError(e));
      // Re-sync in case the server actually did succeed (network blip).
      void fetchRun(prevRun.run_id);
    } finally {
      setLoading(false);
    }
  }

  async function onRefresh() {
    if (run === null) return;
    setLoading(true);
    try {
      const r = await fetchRun(run.run_id);
      if (r && !TERMINAL_STATUSES.has(r.status)) {
        startPoll(r.run_id);
      } else {
        clearPoll();
      }
    } finally {
      setLoading(false);
    }
  }

  const hasLiveRun = run !== null && !TERMINAL_STATUSES.has(run.status);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Drill lifecycle</CardTitle>
        <CardDescription>
          {scenario === null
            ? "Pick a scenario above to start a drill."
            : `Scenario: ${scenario.name}`}
          {run !== null && (
            <span className="ml-2 font-mono">· run #{run.run_id}</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="font-mono whitespace-pre-wrap">{error}</span>
            </div>
            {/*
              Q15: only show "Open Config" when the error is a PVE /
              bridge / credential issue (errorKind === "generic").
              Rate-limit errors get a different banner below.
              The legacy banner with "Open Config" was misleading
              for rate limits because the operator would click it,
              find PVE/bridges are fine, and never realize they
              just need to wait.
            */}
            {errorKind !== "rate_limited" && onNavigateToConfig && (
              <Button
                size="sm"
                variant="outline"
                className="mt-2"
                onClick={onNavigateToConfig}
              >
                <Settings className="h-3.5 w-3.5" />
                <span className="ml-1">Open Config</span>
              </Button>
            )}
            {errorKind === "rate_limited" && (
              <p className="mt-2 text-xs text-muted-foreground">
                Need to inspect cluster health instead?{" "}
                {onNavigateToConfig && (
                  <button
                    type="button"
                    className="underline underline-offset-2 hover:text-foreground"
                    onClick={onNavigateToConfig}
                  >
                    Open the Config tab
                  </button>
                )}
                . The limit resets when the window expires (no
                manual action required -- try again in a few
                minutes, or restart the stack with a higher
                ``DRILL_START_LIMIT`` env var).
              </p>
            )}
          </div>
        )}

        {canStart && scenario !== null && (run === null || !hasLiveRun) && (
          <div className="flex items-center gap-2">
            <Button onClick={onStart} disabled={loading || scenario === null}>
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-2 h-4 w-4" />
              )}
              Start drill
            </Button>
            {/* Q20: always-visible Stop button (disabled until a
                live run exists). Q19's gate ``canStop && hasLiveRun``
                hid it for first-time operators who hadn't yet
                started a drill -- they'd never learn the capability
                exists. Now it sits next to Start as a discoverable
                affordance; the button is greyed out until the
                operator has a running drill to stop. */}
            {canStop && (
              <Button
                variant="outline"
                onClick={onStop}
                disabled={loading || !hasLiveRun}
                data-testid="lifecycle-stop"
                title="Operator force-stop — only enabled while a drill is live."
              >
                <CircleStop className="mr-2 h-4 w-4" />
                Stop
              </Button>
            )}
          </div>
        )}

        {run !== null && (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span
                className={
                  "inline-block rounded px-2 py-0.5 font-mono text-xs " +
                  (TERMINAL_STATUSES.has(run.status)
                    ? "bg-emerald-900/40 text-emerald-200"
                    : "bg-amber-900/40 text-amber-200")
                }
              >
                {run.status}
              </span>
              {run.started_by && (
                <span className="text-muted-foreground">by {run.started_by}</span>
              )}
              {run.started_at && (
                <span className="text-muted-foreground">
                  started {new Date(run.started_at).toLocaleString()}
                </span>
              )}
              {run.duration_sec !== null && run.duration_sec !== undefined && (
                <span className="text-muted-foreground">
                  duration {Math.round(run.duration_sec)}s
                </span>
              )}
              <Button
                variant="ghost"
                size="icon"
                onClick={onRefresh}
                disabled={loading}
                aria-label="Refresh"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>

            {/* Q23-#2 + #5: post-run actions.
                Visible only when the run is terminal -- Restart
                starts a new drill with the same scenario_id; Save
                bookmarks the run as a reusable template. */}
            {TERMINAL_STATUSES.has(run.status) && (
              <div
                className="flex flex-wrap items-center gap-2"
                data-testid="lifecycle-post-run-actions"
              >
                {canRestart && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onRestart}
                    disabled={loading}
                    data-testid="lifecycle-restart"
                    title="Start a new drill with the same scenario. The current run is left as-is."
                  >
                    {loading ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <RotateCw className="mr-1 h-3 w-3" />
                    )}
                    Restart drill
                  </Button>
                )}
                {canSaveAsTemplate && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onSaveAsTemplate}
                    disabled={loading || savingAsTemplate}
                    data-testid="lifecycle-save-as-template"
                    title="Bookmark this run as a reusable template."
                  >
                    {savingAsTemplate ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <BookMarked className="mr-1 h-3 w-3" />
                    )}
                    Save as template
                  </Button>
                )}
                {savedTemplateName !== null && (
                  <span
                    className="text-xs text-emerald-300"
                    data-testid="lifecycle-saved-toast"
                  >
                    Saved as &quot;{savedTemplateName}&quot;.
                  </span>
                )}
              </div>
            )}

            {run.assets && run.assets.length > 0 && (
              <div>
                <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Assets ({run.assets.length})
                </h4>
                <ul className="divide-y divide-border rounded-md border border-border">
                  {run.assets.map((a) => (
                    <li
                      key={a.asset_id ?? `${a.role}-${a.pve_vmid}`}
                      className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                    >
                      <div>
                        <div className="font-mono">{a.role ?? a.kind ?? "asset"}</div>
                        <div className="text-xs text-muted-foreground">
                          {a.template ?? ""}
                          {a.pve_vmid !== null && a.pve_vmid !== undefined
                            ? ` · vmid=${a.pve_vmid}`
                            : ""}
                          {a.pve_ip ? ` · ${a.pve_ip}` : ""}
                        </div>
                      </div>
                      <span className="font-mono text-xs text-muted-foreground">
                        {a.status ?? "?"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* VPN config download — shown while a drill is live or just finished */}
            {run && (
              <VpnDownloadButton runStatus={run.status} />
            )}

            {canCancelThis && hasLiveRun && (
              <div className="flex items-center gap-2">
                <Input
                  placeholder="cancel reason"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  className="max-w-xs"
                />
                <Button variant="destructive" onClick={onCancel} disabled={loading}>
                  <Square className="mr-2 h-4 w-4" /> Cancel
                </Button>
              </div>
            )}

            {canCancel && !canCancelThis && hasLiveRun && (
              <div className="text-xs italic text-muted-foreground">
                You can only cancel runs you started (this run was started
                by {run.started_by ?? "?"}).
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// VpnDownloadButton
// ---------------------------------------------------------------------------
// Appears on any live or recently-completed drill. Calls
// GET /api/v1/auth/vpn-config, which returns the .conf text, then
// triggers a browser download. The button is self-contained so it
// can be added to other cards later without prop-drilling.

function VpnDownloadButton({ runStatus }: { runStatus: string }) {
  const [downloading, setDownloading] = useState(false);
  const [vpnIp, setVpnIp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const SHOW_STATUSES = new Set([
    "pending", "running",
    "succeeded", "completed",
    "failed", "timeout", "cancelled", "canceled",
  ]);
  if (!SHOW_STATUSES.has(runStatus)) return null;

  async function download() {
    setDownloading(true);
    setError(null);
    try {
      const data = await api.get<{
        config: string;
        filename: string;
        client_ip: string;
        server_ip: string;
        allowed_ips: string;
      }>("/api/v1/auth/vpn-config");

      setVpnIp(data.client_ip);

      // Trigger browser download of the .conf file
      const blob = new Blob([data.config], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setError(`VPN config failed: ${detailFromError(e)}`);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Shield className="h-4 w-4 text-primary shrink-0" />
        Connect via WireGuard VPN
      </div>
      <p className="text-xs text-muted-foreground">
        Download your personal VPN config, import it into the{" "}
        <a
          href="https://www.wireguard.com/install/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          WireGuard client
        </a>
        , then connect. Your drill VMs will be reachable directly.
      </p>
      {vpnIp && (
        <p className="font-mono text-xs text-emerald-400">
          Your VPN IP: {vpnIp}
        </p>
      )}
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
      <Button
        size="sm"
        variant="outline"
        onClick={download}
        disabled={downloading}
      >
        {downloading ? (
          <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="mr-2 h-3.5 w-3.5" />
        )}
        {downloading ? "Generating…" : "Download VPN config"}
      </Button>
    </div>
  );
}