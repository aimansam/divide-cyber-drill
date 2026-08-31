/**
 * OperatorConsoleCard — range operator's lens.
 *
 * The "what's running right now + what do I do about it" view for
 * the lead/admin. Shows every run that's currently RUNNING or
 * PENDING with quick-action buttons:
 *
 *   * Refresh (manual poll)
 *   * Stop    — POST /api/v1/drills/{id}/stop (admin/lead only)
 *   * Reset   — POST /api/v1/drills/{id}/reset  (deferred to F7)
 *   * Inject  — opens a future "inject a flag / event" modal
 *               (deferred to F5/F8)
 *
 * The Stop button is real (the endpoint exists, F2.5 added the
 * matrix entry). Reset + Inject are stubs that surface a clear
 * "Coming with F7" message so the operator knows what to expect.
 *
 * "Real cyber ranges call this the Range Operator console —
 * RangeForce, Cyberbit, and Immersive Labs all have one."
 */

import { useEffect, useMemo, useState } from "react";
import {
  CircleStop,
  Loader2,
  Power,
  RefreshCw,
  RotateCcw,
  Siren,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "./empty-state";
import { StatusPill } from "./status-pill";
import { InjectEventModal } from "./inject-event-modal";
import { api, ApiError, detailFromError } from "@/lib/api";
import { formatRelative } from "@/lib/format";

interface LiveRun {
  /**
   * Q20: align with the wire shape -- the API serialises the run
   * row as ``run_id``. Pre-Q20 this interface declared ``id`` which
   * never matched, so ``r.id`` was ``undefined`` at every callsite
   * below and the Stop / Reset buttons on this card were silently
   * calling ``POST /api/v1/drills/undefined/{stop,reset}`` -- the
   * 404 from those calls failed silently inside the try/catch and
   * the operator saw no feedback.
   */
  run_id: number;
  scenario_id?: number;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
}

interface RunsPayload {
  items?: LiveRun[];
}

export function OperatorConsoleCard() {
  const [runs, setRuns] = useState<LiveRun[]>([]);
  // Q23-B4+B5: split "loading" (initial fetch -- show the
  // "Loading…" placeholder) from "refreshing" (background poll
  // -- keep the list rendered, just spin the Refresh icon).
  // Pre-fix, every 5s poll set loading=true and unmounted the
  // list for ~100ms which made the UI feel broken.
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  /**
   * Q21: runs the operator has just stopped in this session.
   * Keyed by run_id, value is the timestamp of the stop.
   * Drives the "Recently stopped" panel below the live list
   * and the "just stopped" badge on a live row that was
   * stopped but hasn't yet polled-out of the live filter.
   */
  const [recentlyStopped, setRecentlyStopped] = useState<Record<number, number>>({});
  // The Inject button opens a modal focused on one run. We
  // store the target runId (or null when closed).
  const [injectForRun, setInjectForRun] = useState<number | null>(null);

  async function load(opts: { initial?: boolean } = {}) {
    if (opts.initial) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const data = await api.get<RunsPayload>("/api/v1/drills");
      setRuns(data.items ?? []);
    } catch (e: unknown) {
      setError(detailFromError(e));
      setRuns([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load({ initial: true });
    const id = window.setInterval(() => load(), 5000);
    return () => window.clearInterval(id);
  }, []);

  const live = useMemo(
    () => runs.filter((r) => r.status === "running" || r.status === "pending"),
    [runs],
  );

  /**
   * Q21: derive the "recently stopped" list from the
   * ``recentlyStopped`` state. We only keep entries < 1 hour
   * old (the 5s poll would otherwise grow this forever during
   * a long operator session). Limited to the last 10 entries
   * newest-first.
   */
  const recentlyStoppedList = useMemo(() => {
    const cutoff = Date.now() - 60 * 60 * 1000;
    return Object.entries(recentlyStopped)
      .filter(([, t]) => t > cutoff)
      .map(([id, t]) => ({ run_id: Number(id), stopped_at: t }))
      .sort((a, b) => b.stopped_at - a.stopped_at)
      .slice(0, 10);
  }, [recentlyStopped]);

  async function stop(id: number) {
    // Q25-P1: confirm before force-stopping a live drill.
    const confirmed = window.confirm(
      `Force-stop drill #${id}? This will immediately kill all running VMs.`,
    );
    if (!confirmed) return;
    setPending(id);
    setError(null);
    setSuccess(null);
    try {
      await api.post(`/api/v1/drills/${id}/stop`);
      // Q21: surface success feedback. Previously the row
      // silently vanished from the live filter and the operator
      // had to trust that the stop worked. We pin the row in
      // ``recentlyStopped`` so the operator gets visual confirmation
      // and the row stays visible until the next poll cycle.
      setRecentlyStopped((prev) => ({ ...prev, [id]: Date.now() }));
      await load();
    } catch (e: unknown) {
      setError(`stop failed: ${detailFromError(e)}`);
    } finally {
      setPending(null);
    }
  }

  async function reset(id: number) {
    // Q25-P1: confirm before resetting a drill.
    const confirmed = window.confirm(
      `Reset drill #${id}? This will restart the drill from the beginning.`,
    );
    if (!confirmed) return;
    setPending(id);
    // Q23-B6: clear any stale success banner from a previous
    // inject. Pre-fix, hitting Reset right after an Inject left
    // the "event injected" banner sitting while the Reset
    // failure rendered below it.
    setSuccess(null);
    try {
      await api.post(`/api/v1/drills/${id}/reset`);
      await load();
    } catch (e: unknown) {
      // Q21: use the structured detail when available so the
      // operator sees the actual error from the API instead of
      // just an HTTP status. The Q23-B2 server-side guard
      // returns 409 with detail "run id=X is live (...); stop
      // it first" for active runs, which we surface verbatim.
      const status = e instanceof ApiError ? e.status : 0;
      if (status === 409) {
        setError(
          `reset failed: ${detailFromError(e)} (save-as-template first if the run has no template)`,
        );
      } else {
        setError(`reset failed: ${detailFromError(e)}`);
      }
    } finally {
      setPending(null);
    }
  }

  function onInjected(runId: number) {
    setSuccess(`event injected into run #${runId}`);
  }

  return (
    <Card data-testid="operator-console-card">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Power className="h-4 w-4 text-muted-foreground" />
              Range operator console
            </span>
          </CardTitle>
          <CardDescription>
            Live runs across the cyber range. Stop / Reset / Inject
            are all wired to their respective backend endpoints
            (F2.5 / F7 / F8). Inject opens a small modal for
            manual telemetry events.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => load()}
          aria-label="Refresh"
          disabled={loading || refreshing}
        >
          {loading || refreshing ? (
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
            data-testid="operator-console-message"
            className="mb-3 rounded-md border border-amber-700 bg-amber-950/40 px-3 py-2 text-sm text-amber-200"
          >
            {error}
          </div>
        )}
        {!error && loading && (
          <p className="text-sm italic text-muted-foreground">Loading…</p>
        )}
        {!error && !loading && live.length === 0 && (
          <EmptyState
            title="No active drills"
            description="The range is quiet. Start a drill on the Operate tab to populate this view."
          />
        )}
        {!error && !loading && live.length > 0 && (
          <ul className="divide-y divide-border" data-testid="operator-live-list" aria-live="polite">
            {live.map((r) => (
              <li
                key={r.run_id}
                className="flex items-center gap-2 px-3 py-2 text-sm"
                data-testid="operator-row"
                data-run-id={r.run_id}
              >
                <span className="font-mono text-xs">#{r.run_id}</span>
                <StatusPill status={r.status} />
                <span className="text-muted-foreground">
                  {r.started_by ?? "—"}
                </span>
                <time
                  className="text-xs text-muted-foreground"
                  dateTime={r.started_at ?? undefined}
                  title={
                    r.started_at
                      ? new Date(r.started_at).toLocaleString()
                      : undefined
                  }
                >
                  {formatRelative(r.started_at)}
                </time>
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => stop(r.run_id)}
                    disabled={pending === r.run_id}
                    data-testid="operator-stop"
                  >
                    <CircleStop className="mr-1 h-3 w-3" />
                    {pending === r.run_id ? "Stopping…" : "Stop"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => reset(r.run_id)}
                    disabled={pending === r.run_id}
                    data-testid="operator-reset"
                  >
                    <RotateCcw className="mr-1 h-3 w-3" />
                    {pending === r.run_id ? "Resetting…" : "Reset"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setInjectForRun(r.run_id)}
                    data-testid="operator-inject"
                  >
                    <Siren className="mr-1 h-3 w-3" />
                    Inject
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {/* Q21: "Recently stopped" panel below the live list.
            Operators need a place to see what they just stopped
            without having to switch to the History tab. Limited
            to the last 10 stops in this session (<1h old). */}
        {recentlyStoppedList.length > 0 && (
          <div className="mt-4 border-t pt-3" data-testid="operator-recently-stopped">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Recently stopped ({recentlyStoppedList.length})
            </div>
            <ul className="space-y-1">
              {recentlyStoppedList.map(({ run_id, stopped_at }) => {
                return (
                  <li
                    key={run_id}
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                    data-testid="operator-recently-stopped-row"
                    data-run-id={run_id}
                  >
                    <span className="font-mono">#{run_id}</span>
                    <StatusPill status="stopped" />
                    <span>stopped {formatRelative(new Date(stopped_at).toISOString())}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CardContent>
      {/* F9.4: success + error banners above the modal so the
          operator gets confirmation feedback when the modal
          closes on a successful inject. */}
      {success !== null && (
        <div
          role="status"
          className="mx-6 mb-4 rounded-md border border-emerald-700 bg-emerald-950/30 px-3 py-2 text-sm text-emerald-200"
          data-testid="operator-success"
        >
          {success}
        </div>
      )}
      {/* F9.4: Inject modal -- mounts only while a target run is
          selected. Closes on backdrop click + Escape key. */}
      {injectForRun !== null && (
        <InjectEventModal
          runId={injectForRun}
          onClose={() => setInjectForRun(null)}
          onInjected={() => onInjected(injectForRun)}
        />
      )}
    </Card>
  );
}
