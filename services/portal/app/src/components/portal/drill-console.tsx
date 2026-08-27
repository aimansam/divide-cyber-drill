/**
 * DrillConsole — the dedicated live-drill view.
 *
 * Replaces the previous "Observe tab = 3 cards stacked" pattern
 * with a single focused surface that shows:
 *
 *   * Status header (RUNNING / SUCCEEDED / FAILED / TIMEOUT) with
 *     "Live" pulse badge while the drill is in flight
 *   * Run metadata: id, scenario name, started_by, duration timer
 *   * Topology preview of the assets (delegates to TopologyGraph)
 *   * Asset table with live IPs (delegates to AssetsCard)
 *   * Audit feed (delegates to AuditExplorerCard)
 *   * Prominent download-report button when terminal
 *   * F9.1: when the Run belongs to an Exercise (multi-team),
 *     the leaderboard + live SOC stream render inline below the
 *     audit feed. Single-team Runs hide these sections; the
 *     Admin tab still surfaces the leaderboard in that flow.
 *   * F11.2: "View debrief" button (next to "Download report")
 *     opens the markdown play-by-play in a new tab once the
 *     run is terminal -- intended for hand-off to leadership.
 *
 * Polling: while RUNNING, every 2s. Otherwise every 5s for
 * post-terminal detail refreshes. The pulse dot stops when the
 * run reaches a terminal status.
 *
 * Why a dedicated component instead of stacking cards in the
 * Observe tab: when a drill is live the operator needs ONE place
 * to look. Scrolling past MyRuns to find RunInspector costs
 * attention; the console puts everything for the active run on
 * one screen. F9 extends that one-screen property to multi-team
 * drills so the operator never has to flip tabs to check the
 * leaderboard or the SOC stream. F11.2 extends it again so the
 * post-drill hand-off lives in the same surface.
 */

import { useEffect, useState } from "react";
import { Activity, Download, FileText, Loader2, RefreshCw } from "lucide-react";
import { api, detailFromError, getToken } from "@/lib/api";
import { AssetsCard } from "./assets-card";
import { AuditExplorerCard } from "./audit-explorer-card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "./empty-state";
import { StatusPill } from "./status-pill";
import { TopologyGraph, type TopologyAsset } from "./topology-graph";
import { LeaderboardCard } from "./leaderboard-card";
import { SocViewCard } from "./soc-view-card";
import type { RunDetail } from "./run-lifecycle-card";

interface DrillConsoleProps {
  pickedRunId: number | null;
  scenarioName?: string;
}

function formatDuration(seconds: number): string {
  if (seconds < 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function DrillConsole({ pickedRunId, scenarioName }: DrillConsoleProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportPending, setReportPending] = useState(false);
  const [tick, setTick] = useState(0); // re-renders the duration timer
  const isLive =
    !!run && (run.status === "running" || run.status === "pending");

  async function load() {
    if (pickedRunId === null) {
      setRun(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await api.get<RunDetail>(`/api/v1/drills/${pickedRunId}`);
      setRun(r);
    } catch (e: unknown) {
      setError(detailFromError(e));
      setRun(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedRunId]);

  // Polling: 2s while live, 5s otherwise.
  useEffect(() => {
    if (pickedRunId === null) return;
    const interval = isLive ? 2000 : 5000;
    const id = window.setInterval(() => {
      load();
      setTick((t) => t + 1);
    }, interval);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedRunId, isLive]);

  // Duration ticker (1s) for the timer display while live.
  useEffect(() => {
    if (!isLive) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [isLive]);

  async function downloadReport() {
    if (pickedRunId === null) return;
    setReportPending(true);
    try {
      const tok = getToken();
      const headers = new Headers();
      if (tok) headers.set("X-Divide-Token", tok);
      const r = await fetch(`/api/v1/drills/${pickedRunId}/report`, {
        headers,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `drill-${pickedRunId}-report.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`report download failed: ${msg}`);
    } finally {
      setReportPending(false);
    }
  }

  // F11.2: open the markdown debrief in a new browser tab. Modern
  // browsers render .md inline (with their own .md viewer); older
  // browsers fall back to plain text which is still readable. The
  // endpoint returns Content-Disposition: inline + text/markdown
  // so the file is "viewable" rather than "downloadable". If the
  // tab fails to open (popup blocker), the error surfaces in the
  // same error alert as the report download.
  function viewDebrief() {
    if (pickedRunId === null) return;
    const tok = getToken();
    if (!tok) {
      setError("debrief: no auth token; sign in first");
      return;
    }
    // We can't pass a custom header to window.open; build a URL
    // that the server accepts via the standard X-Divide-Token
    // header. Since window.open drops headers, we open a
    // blob: URL instead: fetch the debrief as text, wrap it
    // in a Blob, and let the browser render it.
    fetch(`/api/v1/drills/${pickedRunId}/debrief.md`, {
      headers: { "X-Divide-Token": tok },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
        return r.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(
          new Blob([blob], { type: "text/markdown;charset=utf-8" }),
        );
        const win = window.open(url, "_blank", "noopener,noreferrer");
        if (win === null) {
          // Popup blocked -- fall back to an in-place link so the
          // operator can right-click + "save as".
          const a = document.createElement("a");
          a.href = url;
          a.download = `drill-${pickedRunId}-debrief.md`;
          a.textContent = "Download debrief";
          a.style.display = "none";
          document.body.appendChild(a);
          a.click();
          a.remove();
        }
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        setError(`debrief fetch failed: ${msg}`);
      });
  }

  if (pickedRunId === null) {
    return (
      <EmptyState
        title="No drill selected"
        description="Pick a run from the History tab to open the drill console, or start a new drill on the Operate tab."
        icon={Activity}
      />
    );
  }

  const durationSec = (() => {
    if (!run?.started_at) return 0;
    const start = new Date(run.started_at).getTime();
    const end =
      run.ended_at ? new Date(run.ended_at).getTime() : Date.now();
    return Math.max(0, Math.floor((end - start) / 1000));
    // tick is referenced so React re-runs the calc each second while live
    void tick;
  })();

  const topologyAssets: TopologyAsset[] = (run?.assets ?? []).map(
    (a, i) => ({
      id: `${a.asset_id ?? i}-${a.role ?? "asset"}`,
      role: a.role ?? "asset",
    }),
  );

  return (
    <div data-testid="drill-console" className="space-y-4">
      <header
        className="flex flex-col gap-3 rounded-md border border-border bg-card p-4 shadow-sm md:flex-row md:items-center md:justify-between"
      >
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-lg font-semibold tracking-tight">
              Drill #{pickedRunId}
            </h2>
            <StatusPill status={run?.status ?? null} />
            {isLive && (
              <span
                data-testid="drill-live-badge"
                className="inline-flex items-center gap-1 rounded-md bg-sky-900/60 px-2 py-0.5 text-xs font-medium text-sky-200 ring-1 ring-inset ring-sky-700"
              >
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300" />
                LIVE
              </span>
            )}
            {loading && (
              <Loader2
                className="h-3.5 w-3.5 animate-spin text-muted-foreground"
                aria-hidden="true"
              />
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {scenarioName ? `Scenario: ${scenarioName} · ` : ""}
            {run?.started_by ?? "—"}
            {durationSec > 0 ? ` · ${formatDuration(durationSec)} elapsed` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={load}
            data-testid="drill-refresh"
            aria-label="Refresh"
          >
            <RefreshCw className="mr-1 h-3 w-3" />
            Refresh
          </Button>
          {run && (run.status === "succeeded" || run.status === "failed" || run.status === "timeout" || run.status === "cancelled" || run.status === "completed" || run.status === "stopped") && (
            <>
              {/* F11.2: leadership-facing markdown play-by-play.
                  Opens in a new tab (modern browsers render .md
                  inline; older fall back to plain text). */}
              <Button
                variant="outline"
                size="sm"
                onClick={viewDebrief}
                data-testid="drill-view-debrief"
                aria-label="View debrief"
              >
                <FileText className="mr-1 h-3 w-3" />
                View debrief
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={downloadReport}
                disabled={reportPending}
                data-testid="drill-download-report"
              >
                <Download className="mr-1 h-3 w-3" />
                {reportPending ? "Preparing…" : "Download report"}
              </Button>
            </>
          )}
        </div>
      </header>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
        >
          {error}
        </div>
      )}

      {run?.error && (
        <div
          role="alert"
          className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
        >
          <span className="font-semibold">Run error:</span> {run.error}
        </div>
      )}

      <section aria-label="Topology">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Network topology
        </h3>
        <TopologyGraph assets={topologyAssets} />
      </section>

      <section aria-label="Assets">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Assets
        </h3>
        <AssetsCard
          pickedRunId={pickedRunId}
          compact
        />
      </section>

      <section aria-label="Audit feed">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Audit feed
        </h3>
        <AuditExplorerCard pickedRunId={pickedRunId} compact />
      </section>

      {/*
        F9.1: For multi-team Runs (run.exercise_id !== null), the
        Observe tab becomes the single live-drill screen -- leaderboard
        + live SOC stream render inline below the audit feed so the
        operator never has to flip tabs during a drill. For
        legacy single-team Runs (exercise_id === null) these sections
        stay hidden; the Admin tab is still the right place for the
        leaderboard in that flow.
      */}
      {run && run.exercise_id != null ? (
        <>
          <section aria-label="Leaderboard" data-testid="drill-leaderboard">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Leaderboard
            </h3>
            {/* F9.2: poll-mode (5s) so the leaderboard ticks live
                alongside the SOC stream. The Admin tab keeps the
                fetch-once-on-mount default (pollIntervalMs=0). */}
            <LeaderboardCard
              exerciseId={run.exercise_id}
              pollIntervalMs={5000}
            />
          </section>
          <section aria-label="Live SOC" data-testid="drill-soc">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Live SOC stream
            </h3>
            <SocViewCard runId={pickedRunId} authToken={getToken()} />
          </section>
        </>
      ) : null}
    </div>
  );
}
