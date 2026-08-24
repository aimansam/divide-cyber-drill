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
import { api, ApiError } from "@/lib/api";

interface LiveRun {
  id: number;
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<RunsPayload>("/api/v1/drills");
      setRuns(data.items ?? []);
    } catch (e: unknown) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setError(msg);
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, []);

  const live = useMemo(
    () => runs.filter((r) => r.status === "running" || r.status === "pending"),
    [runs],
  );

  async function stop(id: number) {
    setPending(id);
    try {
      await api.post(`/api/v1/drills/${id}/stop`);
      await load();
    } catch (e: unknown) {
      const status = e instanceof ApiError ? e.status : 0;
      setError(`stop failed: HTTP ${status || "unknown"}`);
    } finally {
      setPending(null);
    }
  }

  function deferred(feature: string) {
    setError(`${feature} — ships with the F7 / F8 plans.`);
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
            Live runs across the cyber range. Stop is wired; reset +
            inject ship with F7 / F8.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={load}
          aria-label="Refresh"
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
          <ul className="divide-y divide-border" data-testid="operator-live-list">
            {live.map((r) => (
              <li
                key={r.id}
                className="flex items-center gap-2 px-3 py-2 text-sm"
                data-testid="operator-row"
                data-run-id={r.id}
              >
                <span className="font-mono text-xs">#{r.id}</span>
                <StatusPill status={r.status} />
                <span className="text-muted-foreground">
                  {r.started_by ?? "—"}
                </span>
                <time className="text-xs text-muted-foreground">
                  {r.started_at
                    ? new Date(r.started_at).toLocaleString()
                    : "—"}
                </time>
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => stop(r.id)}
                    disabled={pending === r.id}
                    data-testid="operator-stop"
                  >
                    <CircleStop className="mr-1 h-3 w-3" />
                    {pending === r.id ? "Stopping…" : "Stop"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deferred("Reset to clean state")}
                    data-testid="operator-reset"
                  >
                    <RotateCcw className="mr-1 h-3 w-3" />
                    Reset
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deferred("Event injection")}
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
      </CardContent>
    </Card>
  );
}
