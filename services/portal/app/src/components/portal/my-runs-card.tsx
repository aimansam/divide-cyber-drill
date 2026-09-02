/**
 * MyRunsCard — list of runs the signed-in user can see.
 *
 * F4-UI: adds a status filter pill row above the list. Lets the
 * operator narrow to "what's currently running" or "what failed
 * last night" without scrolling.
 *
 * The server-side visibility filter lives in
 * services/api/app/services/authorization.py::visible_runs_query
 * (see commit 4d840f9). For a red/blue token the list is filtered
 * to `started_by = token.sub`; for admin/lead/observer it's the
 * full table. This card trusts that filter — it doesn't try to
 * re-implement it client-side.
 *
 * Roles:
 *   red, blue: shown as "My runs"
 *   admin, lead, observer: shown as "All runs"
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Download,
  Loader2,
  RotateCcw,
  Eye,
  CircleStop,
  Activity,
  Radio,
  ChevronRight,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, detailFromError, getToken } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { StatusPill } from "./status-pill";
import type { Role } from "@/lib/roles";

export interface RunRow {
  /**
   * Q20: the API serialises this row as ``run_id`` (not ``id``).
   * Pre-Q20 the portal declared ``id: number`` and read ``r.id``,
   * but the wire shape never carried that key — every row
   * rendered as ``run # · scenario 1`` with the number blank,
   * and ``r.id === pickedRunId`` was always false so picked
   * highlighting + cross-card run selection was broken. Align
   * the TS shape with what the API actually returns.
   */
  run_id: number;
  scenario_id?: number;
  status: string;
  started_by?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
}

interface RunsPayload {
  items?: RunRow[];
  total?: number;
}

const ALL_RUNS_ROLES: readonly Role[] = ["admin", "lead", "observer"];

const FILTER_OPTIONS = [
  "all",
  "pending",
  "running",
  "succeeded",
  "failed",
  "timeout",
  "cancelled",
  "stopped", // Q18: Q17 added the run.stopped audit action + the
            // "stopped" Run.status (set by /drills/{id}/stop),
            // so users need a way to filter for it.
] as const;

export function MyRunsCard({
  meRole,
  pickedRunId,
  onPick,
  compact = false,
  liveOnly = false,
}: {
  meRole: Role;
  pickedRunId: number | null;
  onPick: (r: RunRow) => void;
  compact?: boolean;
  liveOnly?: boolean;
}) {
  const [items, setItems] = useState<RunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<(typeof FILTER_OPTIONS)[number]>(
    "all",
  );
  // Q27: track which row is selected for inline action buttons
  const [selectedRowId, setSelectedRowId] = useState<number | null>(null);
  // Q27: track in-flight action to show spinner
  const [actionPending, setActionPending] = useState<{
    runId: number;
    action: string;
  } | null>(null);
  // Q27: ref for click-outside-to-deselect
  const listRef = useRef<HTMLUListElement>(null);
  const isAllView = ALL_RUNS_ROLES.includes(meRole);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<RunsPayload>("/api/v1/drills");
      setItems(data.items ?? []);
    } catch (e: unknown) {
      setError(detailFromError(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Refresh every 5s so the History tab stays current without
    // a manual click.
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, []);

  // Q27: click-outside-to-deselect
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (listRef.current && !listRef.current.contains(event.target as Node)) {
        setSelectedRowId(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Q27: action handlers
  async function handleStop(runId: number) {
    setActionPending({ runId, action: "stop" });
    try {
      await api.post(`/api/v1/drills/${runId}/stop`);
      await load(); // refresh list
    } catch (e: unknown) {
      setError(`Stop failed: ${detailFromError(e)}`);
    } finally {
      setActionPending(null);
    }
  }

  async function handleRestart(run: RunRow) {
    if (!run.scenario_id) {
      setError("Cannot restart: no scenario_id on this run");
      return;
    }
    setActionPending({ runId: run.run_id, action: "restart" });
    try {
      await api.post("/api/v1/drills", { scenario_id: run.scenario_id });
      await load(); // refresh list
    } catch (e: unknown) {
      setError(`Restart failed: ${detailFromError(e)}`);
    } finally {
      setActionPending(null);
    }
  }

  async function handleReport(runId: number) {
    setActionPending({ runId, action: "report" });
    try {
      const tok = getToken();
      const headers = new Headers();
      if (tok) headers.set("X-Divide-Token", tok);
      const r = await fetch(`/api/v1/drills/${runId}/report`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `drill-${runId}-report.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`Report download failed: ${msg}`);
    } finally {
      setActionPending(null);
    }
  }

  const filtered = useMemo(() => {
    let result = items;
    if (liveOnly) {
      result = result.filter((r) => r.status === "running" || r.status === "pending");
    }
    if (statusFilter === "all") return result;
    return result.filter((r) => r.status === statusFilter);
  }, [items, statusFilter, liveOnly]);

  return (
    <Card className={compact ? "h-full border-border/80 shadow-sm flex flex-col" : ""}>
      <CardHeader className={compact ? "p-3 pb-2 space-y-2" : "flex-row items-center justify-between space-y-0"}>
        <div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Activity className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className={compact ? "text-sm font-semibold leading-none" : ""}>
                  {liveOnly ? "Live Drills" : isAllView ? "All Runs" : "My Runs"}
                </CardTitle>
                {compact && (
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    {filtered.length} active · select to view
                  </p>
                )}
              </div>
            </div>
            {liveOnly && filtered.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-medium text-sky-400 border border-sky-500/30">
                <Radio className="h-2.5 w-2.5 animate-pulse text-sky-400" />
                Live
              </span>
            )}
          </div>
          {!compact && (
            <CardDescription>
              {items.length} run{items.length === 1 ? "" : "s"} visible to you ·
              click one to inspect it
            </CardDescription>
          )}
          {!liveOnly && (
          <div
            className={compact ? "mt-1 flex flex-wrap items-center gap-0.5" : "mt-2 flex flex-wrap items-center gap-1"}
            data-testid="my-runs-filter"
          >
            {FILTER_OPTIONS.map((opt) => {
              const count =
                opt === "all"
                  ? items.length
                  : items.filter((r) => r.status === opt).length;
              const isEmpty = count === 0 && opt !== "all";
              return (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setStatusFilter(opt)}
                  data-active={statusFilter === opt ? "true" : "false"}
                  data-testid={`my-runs-filter-${opt}`}
                  disabled={isEmpty}
                  className={
                    statusFilter === opt
                      ? "rounded bg-primary/15 px-1.5 py-0.25 text-[10px] text-primary ring-1 ring-primary/30"
                      : isEmpty
                        ? "rounded bg-secondary/10 px-1.5 py-0.25 text-[10px] text-muted-foreground/40 cursor-not-allowed"
                        : "rounded bg-secondary/40 px-1.5 py-0.25 text-[10px] text-secondary-foreground hover:bg-secondary"
                  }
                >
                  {opt} ({count})
                </button>
              );
            })}
          </div>
          )}
        </div>
      </CardHeader>
      <CardContent className={compact ? "px-3 pb-3 pt-0 flex-1" : ""}>
        {error && <div className="text-sm text-destructive">{error}</div>}
        {loading && items.length === 0 && (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading runs…
          </div>
        )}
        {!error && !loading && filtered.length === 0 && (
          <div className="rounded-lg border border-dashed border-border/80 p-5 text-center text-xs text-muted-foreground">
            {liveOnly
              ? "No live drills running right now. Launch one in Operate."
              : statusFilter === "all"
                ? isAllView
                  ? "No drills on record. Start one from the scenario list."
                  : "You haven't started any drills yet. Pick a scenario above to run one."
                : `No runs match the ${statusFilter} filter.`}
          </div>
        )}
        <ul
          ref={listRef}
          className={compact ? "space-y-1.5 max-h-[calc(100vh-200px)] overflow-y-auto pr-0.5" : "divide-y divide-border max-h-96 overflow-y-auto"}
          aria-live="polite"
        >
          {filtered.map((r) => {
            const isPicked = r.run_id === pickedRunId;
            const isSelected = selectedRowId === r.run_id;
            const isPending = actionPending?.runId === r.run_id;
            const isLive = r.status === "running" || r.status === "pending";
            const isTerminal = [
              "succeeded", "completed", "failed", "timeout",
              "stopped", "cancelled", "canceled",
            ].includes(r.status);

            if (compact) {
              return (
                <li key={r.run_id}>
                  <button
                    type="button"
                    onClick={() => {
                      onPick(r);
                      setSelectedRowId((prev) =>
                        prev === r.run_id ? null : r.run_id,
                      );
                    }}
                    className={
                      "group relative w-full rounded-lg border text-left p-3 transition-all duration-200 overflow-hidden " +
                      (isPicked
                        ? "border-primary bg-primary/10 shadow-sm ring-1 ring-primary/30"
                        : "border-border/60 bg-card/60 hover:border-primary/40 hover:bg-accent/40")
                    }
                  >
                    {/* Full-height accent bar */}
                    <div
                      className={
                        "absolute left-0 top-0 bottom-0 w-1 transition-colors " +
                        (isPicked ? "bg-primary" : "bg-transparent group-hover:bg-primary/30")
                      }
                    />
                    <div className="flex items-start justify-between gap-2 pl-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-mono text-xs font-semibold text-foreground group-hover:text-primary transition-colors">
                            Drill #{r.run_id}
                          </span>
                          {r.scenario_id !== undefined && (
                            <span className="inline-flex items-center rounded border border-border/50 bg-muted/40 px-1 py-0.2 text-[9px] font-mono text-muted-foreground">
                              scen:{r.scenario_id}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
                          <span>{r.started_by ?? "—"}</span>
                          {r.started_at && (
                            <span>· {formatRelative(r.started_at)}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <StatusPill status={r.status} />
                        <ChevronRight
                          className={
                            "h-3.5 w-3.5 transition-all " +
                            (isPicked
                              ? "text-primary translate-x-0.5"
                              : "text-muted-foreground/40 group-hover:text-muted-foreground group-hover:translate-x-0.5")
                          }
                        />
                      </div>
                    </div>
                  </button>
                </li>
              );
            }

            return (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => {
                    onPick(r);
                    setSelectedRowId((prev) =>
                      prev === r.run_id ? null : r.run_id,
                    );
                  }}
                  className={
                    "flex w-full items-center justify-between gap-3 px-2 py-3 text-left transition-colors hover:bg-accent " +
                    (isPicked ? "bg-accent" : "")
                  }
                >
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <div className="min-w-0">
                      <div className="font-mono text-sm">
                        run #{r.run_id}
                        {r.scenario_id !== undefined ? (
                          <span className="text-muted-foreground">
                            {" "}
                            · scenario {r.scenario_id}
                          </span>
                        ) : null}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {r.started_by ?? "—"}
                      </div>
                    </div>

                    {/* Q27: inline action buttons - hidden in compact mode */}
                    {!compact && isSelected && (
                      <div
                        className="flex items-center gap-1 ml-2"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {isLive && (
                          <>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleStop(r.run_id)}
                              disabled={isPending}
                              title="Stop this drill"
                            >
                              {isPending && actionPending?.action === "stop" ? (
                                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              ) : (
                                <CircleStop className="mr-1 h-3 w-3" />
                              )}
                              Stop
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => onPick(r)}
                              title="View in Observe tab"
                            >
                              <Eye className="mr-1 h-3 w-3" />
                              View
                            </Button>
                          </>
                        )}
                        {isTerminal && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => onPick(r)}
                              title="View in Observe tab"
                            >
                              <Eye className="mr-1 h-3 w-3" />
                              View
                            </Button>
                            {["succeeded", "completed", "failed", "stopped"].includes(r.status) && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleRestart(r)}
                                disabled={isPending}
                                title="Restart with same scenario"
                              >
                                {isPending && actionPending?.action === "restart" ? (
                                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                ) : (
                                  <RotateCcw className="mr-1 h-3 w-3" />
                                )}
                                Restart
                              </Button>
                            )}
                            {["succeeded", "completed"].includes(r.status) && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleReport(r.run_id)}
                                disabled={isPending}
                                title="Download report"
                              >
                                {isPending && actionPending?.action === "report" ? (
                                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                ) : (
                                  <Download className="mr-1 h-3 w-3" />
                                )}
                                Report
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <StatusPill status={r.status} />
                    {r.started_at ? (
                      <span className="text-xs text-muted-foreground">
                        {formatRelative(r.started_at)}
                      </span>
                    ) : null}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
