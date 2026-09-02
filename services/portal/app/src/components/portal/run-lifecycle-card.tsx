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
  Clock,
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
  X,
  Target,
  Zap,
  Skull,
  FileCode2,
  Eye,
  Server,
  Clipboard,
  ClipboardCheck,
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
import { formatDuration, formatRelative } from "@/lib/format";
import { hasRole, type Role } from "@/lib/roles";
import type { Scenario } from "@/components/portal/scenarios-card";
import { StatusPill } from "./status-pill";
import { type AuditRow, tone, actionLabel, relativeTime } from "./audit-explorer-card";
import { useToasts } from "./toast";

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
  "succeeded", // Q25: the wire status for a cleanly-finished drill; without
               // this the card treats succeeded as live and shows Cancel/Stop
               // buttons, and hides the post-run Restart/Save-as-template block.
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
  // F6: team name for multi-team exercises (red/blue/white).
  team?: string | null;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
  timeout_sec?: number | null;
  score_blue?: number | null;
  score_red?: number | null;
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
  /**
   * Optional: navigate to the Observe tab for a specific run.
   */
  onNavigateToObserve?: (runId: number) => void;
}
export function RunLifecycleCard({
  meSub,
  meRole,
  scenario,
  pickedRunId,
  onNavigateToConfig,
  onNavigateToObserve,
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
  const [latestAudit, setLatestAudit] = useState<AuditRow | null>(null);
  // Countdown timer state for live drills.
  const [timeLeftSec, setTimeLeftSec] = useState<number | null>(null);
  const [extendingTimeout, setExtendingTimeout] = useState(false);
  const toasts = useToasts();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [copiedVmid, setCopiedVmid] = useState<number | null>(null);

  async function copySsh(text: string, vmid: number | null) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopiedVmid(vmid);
      setTimeout(() => setCopiedVmid(null), 1500);
    } catch {
      // ignore
    }
  }

  const prevStatusRef = useRef<string | null>(null);

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

  async function fetchLatestAudit(id: number) {
    try {
      const data = await api.get<{ items?: AuditRow[] }>(`/api/v1/drills/${id}/audit`);
      if (data && data.items && data.items.length > 0) {
        setLatestAudit(data.items[data.items.length - 1]);
      } else {
        setLatestAudit(null);
      }
    } catch {
      // Non-blocking
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
        void fetchLatestAudit(id);
        if (r) {
          // Detect status transitions and show toasts
          const prevStatus = prevStatusRef.current;
          if (prevStatus && prevStatus !== r.status && TERMINAL_STATUSES.has(r.status)) {
            if (r.status === "succeeded" || r.status === "completed") {
              toasts.success(`Drill #${r.run_id} completed successfully`);
            } else if (r.status === "failed") {
              toasts.error(`Drill #${r.run_id} failed`);
            } else if (r.status === "timeout") {
              toasts.error(`Drill #${r.run_id} timed out`);
            } else if (r.status === "stopped") {
              toasts.info(`Drill #${r.run_id} stopped`);
            } else if (r.status === "cancelled" || r.status === "canceled") {
              toasts.info(`Drill #${r.run_id} cancelled`);
            }
          }
          prevStatusRef.current = r.status;
          if (TERMINAL_STATUSES.has(r.status)) {
            clearPoll();
          }
        }
      });
    }, 2000);
  }

  useEffect(() => {
    if (pickedRunId === null) {
      setRun(null);
      clearPoll();
      setTimeLeftSec(null);
      return;
    }
    // Q25: reset cancel reason when switching runs so the operator
    // doesn't accidentally cancel a different run with a stale reason.
    setCancelReason("user requested");
    setLoading(true);
    fetchRun(pickedRunId)
      .then((r) => {
        void fetchLatestAudit(pickedRunId);
        if (r) {
          prevStatusRef.current = r.status;
          if (!TERMINAL_STATUSES.has(r.status)) {
            startPoll(r.run_id);
          }
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
      toasts.success(`Drill #${created.run_id} started successfully`);
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
    // Q25-P1: confirm before killing a live drill.
    const confirmed = window.confirm(
      `Cancel drill #${run.run_id}? This will stop all running VMs and mark the drill as cancelled.`,
    );
    if (!confirmed) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await api.post<RunDetail>(
        `/api/v1/drills/${run.run_id}/cancel`,
        { reason: cancelReason, actor: meSub },
      );
      setRun(updated);
      toasts.success(`Drill #${run.run_id} cancelled`);
      clearPoll();
    } catch (e: unknown) {
      setError(detailFromError(e));
      toasts.error(`Failed to cancel drill: ${detailFromError(e)}`);
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
    if (run === null) {
      setError("No run selected.");
      return;
    }
    // Allow restart if either scenario is picked OR run has scenario_id.
    if (scenario === null && run.scenario_id === undefined) {
      // Q25: surface a hint instead of silently returning. Pre-fix,
      // clicking Restart with no scenario picked did nothing and the
      // operator had no feedback.
      setError("Pick a scenario first, then restart.");
      return;
    }
    // Q25-P1: confirm before starting a new drill (allocates new VMs).
    const scenarioName = scenario?.name ?? (run.scenario_id !== undefined ? `scenario #${run.scenario_id}` : "unknown");
    const confirmed = window.confirm(
      `Restart drill with scenario "${scenarioName}"? A new run will be created with fresh VMs.`,
    );
    if (!confirmed) return;
    setLoading(true);
    setError(null);
    setErrorKind(null);
    try {
      const created = await api.post<RunDetail>("/api/v1/drills", {
        scenario_id: run.scenario_id ?? scenario?.id,
      });
      setRun(created);
      toasts.success(`Drill #${created.run_id} restarted`);
      if (!TERMINAL_STATUSES.has(created.status)) {
        startPoll(created.run_id);
      }
    } catch (e: unknown) {
      const structured = parseErrorKind(e);
      setErrorKind(
        structured.kind === "rate_limited" ? "rate_limited" : "generic",
      );
      setError(structured.message ?? detailFromError(e));
      toasts.error(`Failed to restart drill`);
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
      toasts.success(`Saved as template "${name}"`);
      // Keep the confirmation visible until the next interaction.
      setTimeout(() => setSavedTemplateName(null), 5000);
      console.log("[Q23] template saved", out);
    } catch (e: unknown) {
      setError(detailFromError(e));
      toasts.error(`Failed to save template`);
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
    // Q25-P1: confirm before force-stopping a live drill.
    const confirmed = window.confirm(
      `Force-stop drill #${run.run_id}? This will immediately kill all running VMs.`,
    );
    if (!confirmed) return;
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
      toasts.success(`Drill #${run.run_id} stopped`);
    } catch (e: unknown) {
      // Revert and surface the error.
      setRun(prevRun);
      setError(detailFromError(e));
      toasts.error(`Failed to stop drill`);
      // Re-sync in case the server actually did succeed (network blip).
      void fetchRun(prevRun.run_id);
    } finally {
      setLoading(false);
    }
  }

  /**
   * Extend the drill timeout by 30 minutes.
   * Calls POST /drills/{id}/extend-timeout with extend_min=30.
   */
  async function onExtendTimeout() {
    if (run === null || !hasLiveRun) return;
    setExtendingTimeout(true);
    setError(null);
    try {
      const result = await api.post<{ new_timeout_sec?: number; extended_min?: number }>(
        `/api/v1/drills/${run.run_id}/extend-timeout`,
        { extend_min: 30 },
      );
      // Update local run state with new timeout.
      if (result.new_timeout_sec !== undefined) {
        setRun({ ...run, timeout_sec: result.new_timeout_sec });
        setTimeLeftSec(result.new_timeout_sec);
      } else if (result.extended_min !== undefined) {
        // Fallback: add 30min to current timeLeftSec.
        setTimeLeftSec((prev) => (prev ?? 0) + result.extended_min! * 60);
      }
      toasts.success(`Drill #${run.run_id} extended by 30 minutes`);
    } catch (e: unknown) {
      setError(detailFromError(e));
      toasts.error(`Failed to extend timeout`);
    } finally {
      setExtendingTimeout(false);
    }
  }

  async function onRefresh() {
    if (run === null) return;
    setLoading(true);
    void fetchLatestAudit(run.run_id);
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

  /**
   * Sync a single asset's status with PVE.
   * Calls POST /drills/{run_id}/assets/{asset_id}/sync-status.
   */
  async function onSyncAsset(assetId: number) {
    if (run === null) return;
    try {
      await api.post(`/api/v1/drills/${run.run_id}/assets/${assetId}/sync-status`);
      // Re-fetch the run to get updated asset state.
      await fetchRun(run.run_id);
      toasts.success(`Asset #${assetId} synced`);
    } catch (e: unknown) {
      setError(detailFromError(e));
      toasts.error(`Failed to sync asset #${assetId}`);
    }
  }

  const hasLiveRun = run !== null && !TERMINAL_STATUSES.has(run.status);

  // Countdown timer: ticks every second while a drill is live.
  useEffect(() => {
    if (run === null || !hasLiveRun || run.timeout_sec === null || run.timeout_sec === undefined) {
      setTimeLeftSec(null);
      return;
    }
    // Compute initial time left from timeout_sec (server returns remaining seconds).
    const computeTimeLeft = () => {
      if (run.timeout_sec === null || run.timeout_sec === undefined) return null;
      return Math.max(0, run.timeout_sec);
    };
    setTimeLeftSec(computeTimeLeft());
    const timer = setInterval(() => {
      setTimeLeftSec((prev) => {
        if (prev === null) return null;
        return Math.max(0, prev - 1);
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [run?.run_id, run?.timeout_sec, hasLiveRun]);
  const scenarioDiffConfig = scenario?.difficulty
    ? {
        beginner: {
          badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
          icon: <Shield className="h-3.5 w-3.5" />,
          label: "Beginner",
        },
        intermediate: {
          badge: "bg-amber-500/10 text-amber-400 border-amber-500/20",
          icon: <Zap className="h-3.5 w-3.5" />,
          label: "Intermediate",
        },
        advanced: {
          badge: "bg-red-500/10 text-red-400 border-red-500/20",
          icon: <Skull className="h-3.5 w-3.5" />,
          label: "Advanced",
        },
      }[scenario.difficulty.toLowerCase()]
    : null;


  return (
    <Card className="h-full border-border/80 shadow-sm flex flex-col">
      <CardHeader className="space-y-4 pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Settings className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold leading-none">
                Drill Workbench
              </CardTitle>
              <CardDescription className="mt-1 text-xs">
                {scenario === null
                  ? "Select a scenario from the sidebar catalog to launch and manage live drills."
                  : run !== null
                    ? `Live drill run #${run.run_id} actively bound to target.`
                    : "Review scenario parameters and launch a fresh drill run."}
              </CardDescription>
            </div>
          </div>
          {onNavigateToConfig && (
            <Button
              variant="outline"
              size="sm"
              onClick={onNavigateToConfig}
              className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
            >
              <FileCode2 className="h-3.5 w-3.5" />
              <span>Scenario Specs</span>
            </Button>
          )}
        </div>

        {/* Selected Scenario Preview Banner */}
        {scenario ? (
          <div className="rounded-xl border border-border/80 bg-gradient-to-r from-card via-muted/20 to-card p-4 transition-all">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-sm text-foreground">
                    {scenario.title || scenario.name}
                  </h3>
                  {scenario.version !== undefined && scenario.version > 1 && (
                    <span className="inline-flex items-center rounded bg-primary/15 px-1.5 py-0.2 text-[10px] font-medium text-primary">
                      v{scenario.version}
                    </span>
                  )}
                  <span className="font-mono text-xs text-muted-foreground/70">
                    ({scenario.name})
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap pt-0.5">
                  {scenarioDiffConfig && (
                    <span
                      className={
                        "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-medium " +
                        scenarioDiffConfig.badge
                      }
                    >
                      {scenarioDiffConfig.icon}
                      {scenarioDiffConfig.label}
                    </span>
                  )}
                  {scenario.duration_min && (
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground/70" />
                      Estimated {scenario.duration_min} mins
                    </span>
                  )}
                  {scenario.run_count !== undefined && (
                    <span className="inline-flex items-center gap-1">
                      <Target className="h-3.5 w-3.5 text-muted-foreground/70" />
                      {scenario.run_count} previous run{scenario.run_count === 1 ? "" : "s"}
                    </span>
                  )}
                  <span className="font-mono text-[11px] text-muted-foreground/50">
                    ID #{scenario.id}
                  </span>
                </div>
              </div>

              {/* Action Buttons inside Scenario Banner */}
              <div className="flex items-center gap-2 shrink-0">
                {canStart && (run === null || !hasLiveRun) && (
                  <Button
                    onClick={onStart}
                    disabled={loading}
                    size="sm"
                    className="h-9 px-4 font-medium shadow-sm"
                  >
                    {loading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4 fill-current" />
                    )}
                    Start drill
                  </Button>
                )}
                {hasLiveRun && run && onNavigateToObserve && (
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => onNavigateToObserve(run.run_id)}
                    className="h-9 px-3 gap-1.5 shadow-sm"
                  >
                    <Eye className="h-4 w-4" />
                    Observe live
                  </Button>
                )}
                {canStop && (
                  <Button
                    variant="outline"
                    onClick={onStop}
                    disabled={loading || !hasLiveRun}
                    data-testid="lifecycle-stop"
                    title="Operator force-stop — only enabled while a drill is live."
                    size="sm"
                    className="h-9 px-3 text-muted-foreground"
                  >
                    <CircleStop className="mr-1.5 h-4 w-4" />
                    Stop
                  </Button>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border/80 p-8 text-center bg-muted/10">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-muted/60 text-muted-foreground mb-3">
              <Target className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium text-foreground">
              No scenario selected
            </p>
            <p className="text-xs text-muted-foreground mt-1 max-w-sm mx-auto">
              Choose a scenario from the sidebar catalog on the left to review its configuration and launch the drill.
            </p>
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-6 pt-2">
        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <span className="font-mono whitespace-pre-wrap flex-1">{error}</span>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setErrorKind(null);
                }}
                className="shrink-0 text-destructive/60 hover:text-destructive transition-colors"
                aria-label="Dismiss error"
              >
                <X className="h-4 w-4" />
              </button>
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

        {canStart && scenario !== null && !hasLiveRun && run !== null && (
          <div className="flex items-center gap-3">
            <Button
              onClick={onStart}
              disabled={loading || scenario === null}
              size="default"
              className="gap-2"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4 fill-current" />
              )}
              Start new run
            </Button>
          </div>
        )}

        {run !== null && (
          <>
            {/* Status banner with visual state indicator */}
            <div
              className={
                "rounded-xl border-l-4 px-5 py-4 " +
                (run.status === "running" || run.status === "pending"
                  ? "border-l-blue-500 bg-blue-500/10"
                  : run.status === "succeeded" || run.status === "completed"
                    ? "border-l-emerald-500 bg-emerald-500/10"
                    : run.status === "failed" || run.status === "timeout"
                      ? "border-l-red-500 bg-red-500/10"
                      : run.status === "stopped" ||
                          run.status === "cancelled" ||
                          run.status === "canceled"
                        ? "border-l-gray-500 bg-gray-500/10"
                        : "border-l-border bg-muted/50")
              }
            >
              <div className="flex flex-wrap items-center gap-4 text-sm">
                <StatusPill status={run.status} />
                {run.team && (
                  <span className="inline-flex items-center rounded bg-secondary px-2.5 py-1 text-xs font-medium uppercase text-secondary-foreground">
                    {run.team}
                  </span>
                )}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted-foreground">
                  {run.started_by && <span>by {run.started_by}</span>}
                  {run.started_at && <span>{formatRelative(run.started_at)}</span>}
                  {run.duration_sec !== null && run.duration_sec !== undefined && (
                    <span className="font-mono text-base font-medium">
                      {run.status === "running" || run.status === "pending"
                        ? "running for "
                        : "duration "}
                      {formatDuration(run.duration_sec)}
                    </span>
                  )}
                  {/* Countdown timer for live drills */}
                  {hasLiveRun && timeLeftSec !== null && (
                    <span
                      className={
                        "font-mono font-semibold " +
                        (timeLeftSec <= 60
                          ? "text-red-500"
                          : timeLeftSec <= 300
                            ? "text-amber-500"
                            : "text-emerald-500")
                      }
                      title="Time remaining before auto-timeout"
                    >
                      <Clock className="mr-1 inline h-3 w-3" />
                      {Math.floor(timeLeftSec / 60)}m {timeLeftSec % 60}s left
                    </span>
                  )}
                </div>
                {/* Extend timeout button for live drills */}
                {hasLiveRun && canStart && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onExtendTimeout}
                    disabled={extendingTimeout}
                    className="h-7 text-xs px-2.5 gap-1 text-sky-400 border-sky-500/30 hover:bg-sky-500/10"
                    title="Extend drill timeout by 30 minutes"
                  >
                    {extendingTimeout ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <Clock className="mr-1 h-3 w-3" />
                    )}
                    +30m Time
                  </Button>
                )}

                <Button
                  variant="ghost"
                  size="icon"
                  className="ml-auto h-7 w-7"
                  onClick={onRefresh}
                  disabled={loading}
                  aria-label="Refresh"
                  title="Refresh status"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              </div>
              {latestAudit && (
                <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/40 pt-1.5 text-xs">
                  <span className="text-[11px] font-medium text-muted-foreground">Latest event:</span>
                  <span
                    className={`inline-block rounded border px-1.5 py-0.2 font-mono text-[10px] font-semibold ${tone(
                      latestAudit.action,
                    )}`}
                  >
                    {actionLabel(latestAudit.action)}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {relativeTime(latestAudit.at)}
                  </span>
                  {latestAudit.actor && (
                    <span className="text-muted-foreground">by {latestAudit.actor}</span>
                  )}
                </div>
              )}
            </div>

            {/* Q27: Post-run actions as inline buttons instead of kebab menu.
                Visible only when the run is terminal -- Restart
                starts a new drill with the same scenario_id; Save
                bookmarks the run as a reusable template. */}
            {TERMINAL_STATUSES.has(run.status) && (canRestart || canSaveAsTemplate) && (
              <div className="flex flex-wrap items-center gap-2" data-testid="lifecycle-post-run-actions">
                {canRestart && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onRestart}
                    disabled={loading}
                    title="Start a new drill with the same scenario. The current run is left as-is."
                  >
                    {loading ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <RotateCw className="mr-1 h-3 w-3" />
                    )}
                    Restart
                  </Button>
                )}
                {canSaveAsTemplate && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onSaveAsTemplate}
                    disabled={loading || savingAsTemplate}
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

            {/* Scores display for completed drills */}
            {TERMINAL_STATUSES.has(run.status) && (run.score_red !== null || run.score_blue !== null) && (
              <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
                <div className="flex items-center gap-4 text-sm">
                  {run.score_red !== null && run.score_red !== undefined && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Red:</span>
                      <span className="font-mono font-semibold text-red-500">{run.score_red}</span>
                    </div>
                  )}
                  {run.score_blue !== null && run.score_blue !== undefined && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Blue:</span>
                      <span className="font-mono font-semibold text-blue-500">{run.score_blue}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Assets section with card-based visual design */}
            {run.assets && run.assets.length > 0 && (
              <div className="rounded-xl border border-border/80 bg-card overflow-hidden shadow-sm">
                <div className="border-b border-border/40 px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Server className="h-3.5 w-3.5 text-primary" />
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Target Assets ({run.assets.length})
                    </h4>
                  </div>
                  {hasLiveRun && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onRefresh}
                      disabled={loading}
                      className="h-6 text-xs gap-1 text-muted-foreground hover:text-foreground"
                      title="Refresh all assets"
                    >
                      <RefreshCw className="h-3 w-3" />
                      <span>Sync all</span>
                    </Button>
                  )}
                </div>
                <div className="p-3 space-y-2">
                  {run.assets.map((a) => {
                    const sshTarget = a.pve_ip
                      ? `divide@${a.pve_ip}`
                      : a.pve_vmid !== null && a.pve_vmid !== undefined
                        ? `vmid=${a.pve_vmid}`
                        : a.role ?? "asset";

                    return (
                      <div
                        key={a.asset_id ?? `${a.role}-${a.pve_vmid}`}
                        className="rounded-lg border border-border/60 bg-muted/15 p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:border-border transition-colors"
                      >
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {a.role ?? a.kind ?? "asset"}
                            </span>
                            {a.template && (
                              <span className="text-[10px] text-muted-foreground truncate">
                                ({a.template})
                              </span>
                            )}
                          </div>
                          <div className="font-mono text-[11px] text-muted-foreground flex flex-wrap items-center gap-2">
                            {a.pve_ip ? (
                              <span className="inline-flex items-center gap-1 rounded bg-sky-500/10 px-1.5 py-0.2 text-[10px] text-sky-400 font-semibold border border-sky-500/20">
                                {sshTarget}
                              </span>
                            ) : (
                              <span className="text-muted-foreground/60">(no IP)</span>
                            )}
                            {a.pve_vmid !== null && a.pve_vmid !== undefined && (
                              <span>vmid={a.pve_vmid}</span>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          <span className="font-mono text-[11px] px-1.5 py-0.5 rounded border border-border/50 bg-muted/30 text-muted-foreground">
                            {a.status ?? "?"}
                          </span>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs gap-1 text-muted-foreground hover:text-foreground"
                            onClick={() => copySsh(sshTarget, a.pve_vmid ?? null)}
                            title="Copy SSH Target"
                          >
                            {copiedVmid === a.pve_vmid ? (
                              <ClipboardCheck className="h-3.5 w-3.5 text-emerald-400" />
                            ) : (
                              <Clipboard className="h-3.5 w-3.5" />
                            )}
                            <span className="text-[10px]">{copiedVmid === a.pve_vmid ? "Copied" : "Copy"}</span>
                          </Button>
                          {hasLiveRun && a.asset_id && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => onSyncAsset(a.asset_id!)}
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                              title="Sync asset status with PVE"
                            >
                              <RefreshCw className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* VPN config download — shown while a drill is live or just finished */}
            {run && (
              <VpnDownloadButton runStatus={run.status} endedAt={run.ended_at} />
            )}

            {/* Danger Zone / Cancel Drill section */}
            {canCancelThis && hasLiveRun && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 transition-all">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-destructive">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>Abort Drill Execution</span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Terminate all cloned VMs on Proxmox and log a cancellation audit event.
                    </p>
                  </div>
                  <div className="flex items-center gap-2 w-full sm:w-auto shrink-0">
                    <Input
                      placeholder="Reason (e.g. user requested)"
                      value={cancelReason}
                      onChange={(e) => setCancelReason(e.target.value)}
                      maxLength={120}
                      className="h-8 text-xs bg-background w-full sm:w-60"
                    />
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={onCancel}
                      disabled={loading}
                      className="h-8 text-xs shrink-0 gap-1.5 shadow-sm font-medium"
                    >
                      <Square className="h-3.5 w-3.5 fill-current" />
                      <span>Cancel drill</span>
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {canCancel && !canCancelThis && hasLiveRun && (
              <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-xs italic text-muted-foreground">
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

function VpnDownloadButton({
  runStatus,
  endedAt,
}: {
  runStatus: string;
  endedAt?: string | null;
}) {
  const [downloading, setDownloading] = useState(false);
  const [vpnIp, setVpnIp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const SHOW_STATUSES = new Set([
    "pending", "running",
    "succeeded", "completed",
    "failed", "timeout", "cancelled", "canceled",
  ]);
  if (!SHOW_STATUSES.has(runStatus)) return null;

  // Q25: hide VPN card for terminal runs older than 30 minutes.
  // The VMs are long gone and the config is stale; showing the
  // button confuses operators browsing old drills.
  if (endedAt && TERMINAL_STATUSES.has(runStatus)) {
    const endedMs = Date.parse(endedAt);
    if (!Number.isNaN(endedMs)) {
      const ageMin = (Date.now() - endedMs) / 60_000;
      if (ageMin > 30) return null;
    }
  }

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
    <div className="rounded-xl border border-border/70 bg-card p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0 border border-primary/20">
          <Shield className="h-4 w-4" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h5 className="text-xs font-semibold text-foreground">WireGuard VPN Access</h5>
            {vpnIp && (
              <span className="font-mono text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.2 rounded">
                IP: {vpnIp}
              </span>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Download your personal profile to route directly to isolated drill VM subnets.
          </p>
          {error && <p className="text-xs text-destructive mt-1">{error}</p>}
        </div>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={download}
        disabled={downloading}
        className="h-8 text-xs shrink-0 gap-1.5 border-border/80 hover:bg-muted font-medium"
      >
        {downloading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Download className="h-3.5 w-3.5 text-primary" />
        )}
        <span>{downloading ? "Generating..." : "Download .conf"}</span>
      </Button>
    </div>
  );
}