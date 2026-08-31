/**
 * CommandCenterCard — the operator's home view.
 *
 * Q27 Phase 1: Hero layout with better visual hierarchy.
 *
 * Sections (top to bottom):
 *   1. Live Status (hero) — large, prominent, with CTA
 *   2. Current Focus — most recent/active drill with quick actions
 *   3. Quick Actions — prioritized grid (most-used first)
 *   4. Recent Activity — with View CTAs
 *   5. System Health — admin only
 *
 * Data sources (all role-filtered server-side):
 *   * GET /api/v1/drills       — list of runs the user can see
 *   * GET /api/v1/admin/assets/orphans — orphan count (admin only)
 *   * GET /api/v1/admin/pve-setup — PVE connection status (admin only)
 */

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Clock,
  FileText,
  LayoutDashboard,
  PlayCircle,
  RefreshCw,
  Server,
  Settings,
  Shield,
  Users,
  XCircle,
} from "lucide-react";
import { api, detailFromError } from "@/lib/api";
import type { Role } from "@/lib/roles";
import { StatusPill } from "./status-pill";
import { EmptyState } from "./empty-state";
import { formatRelative } from "@/lib/format";

export interface CommandCenterRunRow {
  run_id: number;
  scenario_id?: number;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  error?: string | null;
}

interface RunsPayload {
  items?: CommandCenterRunRow[];
  total?: number;
}

interface OrphanPayload {
  items?: { asset_id: number; run_id: number; pve_vmid: number }[];
  total?: number;
}

interface PveSetupPayload {
  configured?: boolean;
  reachable?: boolean;
  bridges?: { name: string; vlan: number }[];
}

interface CommandCenterCardProps {
  meRole: Role;
  meSub: string | null;
  onNavigate: (view: "operate" | "observe" | "admin" | "config" | "history") => void;
  onPickRun: (run: CommandCenterRunRow) => void;
}

interface QuickAction {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  target: "operate" | "observe" | "admin" | "config" | "history";
  minRole: Role[];
  description: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  {
    label: "Start Drill",
    icon: PlayCircle,
    target: "operate",
    minRole: ["admin", "lead", "red"],
    description: "Pick a scenario and launch a new drill",
  },
  {
    label: "View Live Drills",
    icon: Activity,
    target: "observe",
    minRole: ["admin", "lead", "observer", "red", "blue"],
    description: "Watch active drills in real-time",
  },
  {
    label: "Check Assets",
    icon: Server,
    target: "observe",
    minRole: ["admin", "lead", "observer"],
    description: "Inspect VM status and sync with PVE",
  },
  {
    label: "Run Report",
    icon: FileText,
    target: "history",
    minRole: ["admin", "lead", "observer"],
    description: "Download drill reports and debriefs",
  },
  {
    label: "Manage Users",
    icon: Users,
    target: "admin",
    minRole: ["admin"],
    description: "Create, edit, or remove operators",
  },
  {
    label: "PVE Ops",
    icon: Shield,
    target: "admin",
    minRole: ["admin"],
    description: "Manage PVE credentials and bridges",
  },
  {
    label: "View Audit",
    icon: Clock,
    target: "admin",
    minRole: ["admin", "lead", "observer"],
    description: "Search the global audit log",
  },
  {
    label: "Config",
    icon: Settings,
    target: "config",
    minRole: ["admin"],
    description: "Configure PVE setup and network",
  },
];

export function CommandCenterCard({
  meRole,
  meSub: _meSub,
  onNavigate,
  onPickRun,
}: CommandCenterCardProps) {
  const [runs, setRuns] = useState<CommandCenterRunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [orphanCount, setOrphanCount] = useState<number | null>(null);
  const [pveStatus, setPveStatus] = useState<{
    configured: boolean;
    reachable: boolean;
    bridgeCount: number;
  } | null>(null);

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

  async function loadAdminData() {
    if (meRole !== "admin" && meRole !== "lead") return;
    try {
      const orphans = await api.get<OrphanPayload>("/api/v1/admin/assets/orphans");
      setOrphanCount(orphans.total ?? orphans.items?.length ?? 0);
    } catch {
      setOrphanCount(null);
    }
    try {
      const pve = await api.get<PveSetupPayload>("/api/v1/admin/pve-setup");
      setPveStatus({
        configured: pve.configured ?? false,
        reachable: pve.reachable ?? false,
        bridgeCount: pve.bridges?.length ?? 0,
      });
    } catch {
      setPveStatus(null);
    }
  }

  useEffect(() => {
    load();
    loadAdminData();
    const id = window.setInterval(() => {
      load();
      loadAdminData();
    }, 30000);
    return () => window.clearInterval(id);
  }, [meRole]);

  const stats = useMemo(() => {
    const live = runs.filter(
      (r) => r.status === "running" || r.status === "pending",
    ).length;
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
    return { live, todayCount, succeeded, failed, successRate };
  }, [runs]);

  const recent = useMemo(
    () =>
      [...runs]
        .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
        .slice(0, 5),
    [runs],
  );

  const visibleActions = QUICK_ACTIONS.filter((a) =>
    a.minRole.includes(meRole),
  );

  // Q27 Phase 1: split actions into primary (first row) and secondary (second row)
  const primaryActions = visibleActions.slice(0, 4);
  const secondaryActions = visibleActions.slice(4);

  // Q27 Phase 1: find the most recent/active drill for "Current Focus"
  const currentFocus = useMemo(() => {
    const live = runs.filter(
      (r) => r.status === "running" || r.status === "pending"
    );
    if (live.length > 0) {
      return live.sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))[0];
    }
    // If no live drills, show the most recent terminal drill
    const terminal = runs.filter(
      (r) => r.status === "succeeded" || r.status === "completed" || r.status === "failed"
    );
    if (terminal.length > 0) {
      return terminal.sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))[0];
    }
    return null;
  }, [runs]);

  if (!loading && runs.length === 0 && meRole) {
    return (
      <div data-testid="command-center-card" className="space-y-6">
        <header className="flex items-center justify-between border-b border-border pb-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Command Center</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Your operator home base. Status, actions, and recent activity at a glance.
            </p>
          </div>
        </header>
        <EmptyState
          title="No runs yet"
          description="Pick a scenario on the Operate tab and start your first drill. The Command Center will populate once you have history."
          icon={LayoutDashboard}
        />
      </div>
    );
  }

  return (
    <div data-testid="command-center-card" className="space-y-6">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-border pb-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Command Center</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Your operator home base. Status, actions, and recent activity at a glance.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
          aria-label="refresh"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </header>

      {/* Q27 Phase 1: Hero - Live Status */}
      <section aria-label="Live status" className="rounded-lg border-2 border-primary/20 bg-gradient-to-br from-primary/5 to-transparent p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              <Activity className="h-6 w-6 text-primary" />
            </div>
            <div>
              <div className="text-3xl font-bold">{stats.live}</div>
              <div className="text-sm text-muted-foreground">
                {stats.live === 0 ? "No active drills" : stats.live === 1 ? "drill running" : "drills running"}
              </div>
            </div>
          </div>
          {stats.live > 0 && (
            <button
              type="button"
              onClick={() => onNavigate("observe")}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              View Live Drills
              <ArrowRight className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Mini stats row */}
        <div className="mt-4 grid grid-cols-3 gap-4 border-t border-border pt-4">
          <div>
            <div className="text-xs text-muted-foreground">Today</div>
            <div className="text-lg font-semibold">{stats.todayCount}</div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Success Rate</div>
            <div className="text-lg font-semibold">
              {stats.successRate === null ? "—" : `${stats.successRate}%`}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Orphans</div>
            <div className="text-lg font-semibold">
              {orphanCount === null ? "—" : orphanCount}
            </div>
          </div>
        </div>
      </section>

      {/* Q27 Phase 1: Current Focus */}
      {currentFocus && (
        <section aria-label="Current focus" className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent">
                <PlayCircle className="h-5 w-5 text-accent-foreground" />
              </div>
              <div>
                <div className="text-sm font-semibold">
                  Run #{currentFocus.run_id} · {currentFocus.status}
                </div>
                <div className="text-xs text-muted-foreground">
                  {currentFocus.started_at ? formatRelative(currentFocus.started_at) : "—"} · by {currentFocus.started_by ?? "—"}
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onNavigate("observe")}
                className="rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
              >
                Observe
              </button>
              <button
                type="button"
                onClick={() => onPickRun(currentFocus)}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                View Details
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Q27 Phase 1: Quick Actions - prioritized rows */}
      <section aria-label="Quick actions">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Quick Actions
        </h3>
        <div className="space-y-2">
          {/* Primary actions (first row) */}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {primaryActions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.label}
                  type="button"
                  onClick={() => onNavigate(action.target)}
                  className="flex items-center gap-3 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-accent"
                >
                  <Icon className="h-5 w-5 text-primary shrink-0" />
                  <div>
                    <div className="text-sm font-medium">{action.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {action.description}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
          {/* Secondary actions (second row, if any) */}
          {secondaryActions.length > 0 && (
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {secondaryActions.map((action) => {
                const Icon = action.icon;
                return (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => onNavigate(action.target)}
                    className="flex items-center gap-3 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-accent"
                  >
                    <Icon className="h-5 w-5 text-muted-foreground shrink-0" />
                    <div>
                      <div className="text-sm font-medium">{action.label}</div>
                      <div className="text-xs text-muted-foreground">
                        {action.description}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {error ? (
        <div
          role="alert"
          className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
        >
          Could not load runs: {error}
        </div>
      ) : null}

      {/* Q27 Phase 1: Recent Activity with View CTAs */}
      <section aria-label="Recent activity">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Recent Activity
          </h3>
          {recent.length > 0 && (
            <button
              type="button"
              onClick={() => onNavigate("history")}
              className="text-xs text-primary hover:underline"
            >
              View all →
            </button>
          )}
        </div>
        {recent.length === 0 ? (
          <p className="text-sm italic text-muted-foreground">
            {loading ? "Loading…" : "No runs in history yet."}
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border bg-card">
            {recent.map((r) => (
              <li
                key={r.run_id}
                className="flex items-center gap-3 px-3 py-2.5 text-sm transition-colors hover:bg-accent/50"
              >
                <button
                  type="button"
                  className="font-mono text-xs font-medium text-primary hover:underline"
                  onClick={() => onPickRun(r)}
                  data-testid="command-center-recent-run"
                >
                  #{r.run_id}
                </button>
                <StatusPill status={r.status} />
                <span className="flex-1 text-sm text-muted-foreground">
                  {r.started_by ?? "—"}
                </span>
                <time className="text-xs text-muted-foreground">
                  {r.started_at ? formatRelative(r.started_at) : "—"}
                </time>
                <button
                  type="button"
                  onClick={() => onPickRun(r)}
                  className="flex items-center gap-1 rounded px-2 py-1 text-xs text-primary hover:bg-accent"
                >
                  View
                  <ArrowRight className="h-3 w-3" />
                </button>
                {r.status === "failed" || r.status === "timeout" ? (
                  <XCircle className="h-3.5 w-3.5 text-red-400" />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* System Health (admin only) */}
      {pveStatus && (meRole === "admin" || meRole === "lead") && (
        <section aria-label="System health">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            System Health
          </h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center gap-2 text-sm">
                <Shield className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">PVE</span>
              </div>
              <div className="mt-1 text-sm font-medium">
                {pveStatus.configured && pveStatus.reachable ? (
                  <span className="text-emerald-400">Connected</span>
                ) : (
                  <span className="text-amber-400">
                    {pveStatus.configured ? "Unreachable" : "Not configured"}
                  </span>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center gap-2 text-sm">
                <Server className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Bridges</span>
              </div>
              <div className="mt-1 text-sm font-medium">
                {pveStatus.bridgeCount} configured
              </div>
            </div>
            <div className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center gap-2 text-sm">
                <Activity className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Orphans</span>
              </div>
              <div className="mt-1 text-sm font-medium">
                {orphanCount === null ? "—" : orphanCount === 0 ? (
                  <span className="text-emerald-400">Clean</span>
                ) : (
                  <span className="text-amber-400">{orphanCount} need cleanup</span>
                )}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
