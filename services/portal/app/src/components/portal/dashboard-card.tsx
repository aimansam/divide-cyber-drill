/**
 * DashboardCard — the operator's home view.
 *
 * Aggregates the data the operator wants to see at a glance when
 * they open the portal:
 *
 *   * "How many drills did we run today?"
 *   * "Is anything running right now?"
 *   * "What's my success rate?"
 *   * "What scenarios have I run recently?"
 *
 * In a real cyber range this view is the first thing a team lead
 * opens in the morning. The same shape exists in TryHackMe ("Home" /
 * "Recently Active"), HackTheBox ("Dashboard"), RangeForce ("Home"
 * / "KPI tiles"), Immersive Labs ("Resilience Score"), and CyLab
 * (picoCTF) ("Activity"). We follow the convention.
 *
 * Data sources (all role-filtered server-side):
 *   * GET /api/v1/drills       — list of runs the user can see
 *   * GET /api/v1/scenarios    — for the "recently used" tile
 *
 * No new backend endpoints needed.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  PlayCircle,
  XCircle,
} from "lucide-react";
import { api, detailFromError } from "@/lib/api";
import type { Role } from "@/lib/roles";
import { KpiTile } from "./kpi-tile";
import { StatusPill } from "./status-pill";
import { EmptyState } from "./empty-state";

export interface DashboardRunRow {
  /**
   * Q20: align with the wire shape -- the API returns ``run_id``,
   * not ``id``. Pre-Q20 the dashboard row text showed ``#undefined``
   * and the onPickRun callback passed NaN to the parent. See the
   * matching fix in ``my-runs-card.tsx``.
   */
  run_id: number;
  scenario_id?: number;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  error?: string | null;
}

interface RunsPayload {
  items?: DashboardRunRow[];
  total?: number;
}

interface DashboardCardProps {
  meRole: Role;
  meSub: string | null;
  onPickScenario?: (scenarioId: number) => void;
  onPickRun?: (runId: number) => void;
}

export function DashboardCard({
  meRole,
  meSub,
  onPickRun,
}: DashboardCardProps) {
  const [runs, setRuns] = useState<DashboardRunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<RunsPayload>("/api/v1/drills");
      setRuns(data.items ?? []);
    } catch (e: unknown) {
      setError(detailFromError(e));
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const inProgress = runs.filter(
      (r) => r.status === "running" || r.status === "pending",
    );
    const today = new Date().toISOString().slice(0, 10);
    const todayCount = runs.filter(
      (r) => r.started_at && r.started_at.slice(0, 10) === today,
    ).length;
    const succeeded = runs.filter(
      (r) => r.status === "succeeded" || r.status === "completed",
    ).length;
    const failed = runs.filter(
      (r) => r.status === "failed" || r.status === "timeout",
    ).length;
    const terminal = succeeded + failed;
    const successRate = terminal === 0 ? null : Math.round((succeeded / terminal) * 100);
    const myRuns = meSub
      ? runs.filter((r) => r.started_by === meSub).length
      : 0;
    return { inProgress, todayCount, succeeded, failed, successRate, myRuns };
  }, [runs, meSub]);

  const recent = useMemo(
    () =>
      [...runs]
        .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
        .slice(0, 5),
    [runs],
  );

  if (!loading && runs.length === 0 && meRole) {
    return (
      <div data-testid="dashboard-card" className="space-y-4">
        <header>
          <h2 className="text-xl font-semibold tracking-tight">Dashboard</h2>
          <p className="text-sm text-muted-foreground">
            Operational metrics and recent activity for the cyber range.
          </p>
        </header>
        <EmptyState
          title="No runs yet"
          description="Pick a scenario on the Operate tab and start your first drill. The dashboard will populate once you have history."
          icon={Activity}
        />
      </div>
    );
  }

  return (
    <div data-testid="dashboard-card" className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold tracking-tight">Dashboard</h2>
        <p className="text-sm text-muted-foreground">
          Operational metrics and recent activity for the cyber range.
        </p>
      </header>

      <section
        aria-label="Key metrics"
        className="grid grid-cols-2 gap-3 md:grid-cols-4"
      >
        <KpiTile
          label="In progress"
          value={stats.inProgress.length}
          sublabel={
            stats.inProgress.length === 0
              ? "no active drills"
              : "running right now"
          }
          icon={PlayCircle}
          tone={stats.inProgress.length > 0 ? "info" : "default"}
          loading={loading}
        />
        <KpiTile
          label="Today"
          value={stats.todayCount}
          sublabel="runs started today"
          icon={Clock}
          tone="default"
          loading={loading}
        />
        <KpiTile
          label="Success rate"
          value={stats.successRate === null ? "—" : `${stats.successRate}%`}
          sublabel={`${stats.succeeded} succeeded · ${stats.failed} failed`}
          icon={CheckCircle2}
          tone={
            stats.successRate === null
              ? "default"
              : stats.successRate >= 80
                ? "success"
                : stats.successRate < 50
                  ? "danger"
                  : "warning"
          }
          loading={loading}
        />
        <KpiTile
          label="My runs"
          value={stats.myRuns}
          sublabel={meSub ? `as ${meSub}` : "—"}
          icon={Activity}
          tone="default"
          loading={loading}
        />
      </section>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
        >
          Could not load runs: {error}
        </div>
      ) : null}

      <section aria-label="Recent runs">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Recent runs
        </h3>
        {recent.length === 0 ? (
          <p className="text-sm italic text-muted-foreground">
            {loading ? "Loading…" : "No runs in history yet."}
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border bg-card">
            {recent.map((r) => (
              <li
                key={r.run_id}
                className="flex items-center gap-3 px-3 py-2 text-sm"
              >
                <button
                  type="button"
                  className="font-mono text-xs text-primary hover:underline"
                  onClick={() => onPickRun?.(r.run_id)}
                  data-testid="dashboard-recent-run"
                >
                  #{r.run_id}
                </button>
                <StatusPill status={r.status} />
                <span className="flex-1 text-muted-foreground">
                  {r.started_by ?? "—"}
                </span>
                <time className="text-xs text-muted-foreground">
                  {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                </time>
                {r.status === "failed" || r.status === "timeout" ? (
                  <XCircle className="h-3.5 w-3.5 text-red-400" />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
