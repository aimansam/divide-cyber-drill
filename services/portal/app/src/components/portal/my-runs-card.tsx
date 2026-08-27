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

import { useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, detailFromError } from "@/lib/api";
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
}: {
  meRole: Role;
  pickedRunId: number | null;
  onPick: (r: RunRow) => void;
}) {
  const [items, setItems] = useState<RunRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<(typeof FILTER_OPTIONS)[number]>(
    "all",
  );
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

  const filtered = useMemo(() => {
    if (statusFilter === "all") return items;
    return items.filter((r) => r.status === statusFilter);
  }, [items, statusFilter]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>{isAllView ? "All runs" : "My runs"}</CardTitle>
          <CardDescription>
            {items.length} run{items.length === 1 ? "" : "s"} visible to you ·
            click one to inspect it
          </CardDescription>
          <div
            className="mt-2 flex flex-wrap items-center gap-1"
            data-testid="my-runs-filter"
          >
            {FILTER_OPTIONS.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => setStatusFilter(opt)}
                data-active={statusFilter === opt ? "true" : "false"}
                data-testid={`my-runs-filter-${opt}`}
                className={
                  statusFilter === opt
                    ? "rounded bg-primary/15 px-2 py-0.5 text-xs text-primary ring-1 ring-primary/30"
                    : "rounded bg-secondary/40 px-2 py-0.5 text-xs text-secondary-foreground hover:bg-secondary"
                }
              >
                {opt}
              </button>
            ))}
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={load} aria-label="Refresh">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </CardHeader>
      <CardContent>
        {error && <div className="text-sm text-destructive">{error}</div>}
        {!error && !loading && filtered.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            {statusFilter === "all"
              ? isAllView
                ? "No drills on record. Start one from the scenario list."
                : "You haven't started any drills yet. Pick a scenario above to run one."
              : `No runs match the ${statusFilter} filter.`}
          </div>
        )}
        <ul className="divide-y divide-border">
          {filtered.map((r) => {
            const isPicked = r.run_id === pickedRunId;
            return (
              <li key={r.run_id}>
                <button
                  onClick={() => onPick(r)}
                  className={
                    "flex w-full items-center justify-between gap-3 px-2 py-3 text-left transition-colors hover:bg-accent " +
                    (isPicked ? "bg-accent" : "")
                  }
                >
                  <div>
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
                  <div className="flex flex-col items-end gap-1">
                    <StatusPill status={r.status} />
                    {r.started_at ? (
                      <span className="text-xs text-muted-foreground">
                        {new Date(r.started_at).toLocaleString()}
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
