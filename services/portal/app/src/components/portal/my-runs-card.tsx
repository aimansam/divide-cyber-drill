/**
 * MyRunsCard — list of runs the signed-in user can see.
 *
 * The server-side visibility filter lives in
 * services/api/app/services/authorization.py::visible_runs_query
 * (see commit 4d840f9). For a red/blue token the list is filtered
 * to `started_by = token.sub`; for admin/lead/observer it's the
 * full table. This card trusts that filter — it doesn't try to
 * re-implement it client-side. (A misbehaving red token that tries
 * to read another run's id will get 403 on the detail endpoint;
 * the list itself just doesn't include those runs.)
 *
 * Roles (M3.2, Half 1):
 *   red, blue: shown as "My runs"
 *   admin, lead, observer: shown as "All runs"
 *
 * Selection: clicking a row sets `pickedRunId` in the parent App,
 * which the RunLifecycleCard reads to drive its detail view.
 * (Half 2's RunInspectorCard will take this over for full detail.)
 */

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type { Role } from "@/lib/roles";

export interface RunRow {
  id: number;
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
  const isAllView = ALL_RUNS_ROLES.includes(meRole);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<RunsPayload>("/api/v1/drills");
      setItems(data.items ?? []);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setError(msg);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // meRole change -> re-fetch (e.g. user re-signed in with a
    // different role; the server filter changes too).
  }, [meRole]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>{isAllView ? "All runs" : "My runs"}</CardTitle>
          <CardDescription>
            {items.length} run{items.length === 1 ? "" : "s"} visible to you ·
            click one to inspect it
          </CardDescription>
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
        {!error && !loading && items.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            {isAllView
              ? "No drills on record. Start one from the scenario list."
              : "You haven't started any drills yet. Pick a scenario above to run one."}
          </div>
        )}
        <ul className="divide-y divide-border">
          {items.map((r) => {
            const isPicked = r.id === pickedRunId;
            return (
              <li key={r.id}>
                <button
                  onClick={() => onPick(r)}
                  className={
                    "flex w-full items-center justify-between gap-3 px-2 py-3 text-left transition-colors hover:bg-accent " +
                    (isPicked ? "bg-accent" : "")
                  }
                >
                  <div>
                    <div className="font-mono text-sm">
                      run #{r.id}
                      {r.scenario_id !== undefined ? (
                        <span className="text-muted-foreground">
                          {" "}
                          · scenario {r.scenario_id}
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span
                        className={
                          "inline-block rounded px-1.5 py-0.5 font-mono " +
                          (r.status === "completed"
                            ? "bg-emerald-900/40 text-emerald-200"
                            : r.status === "cancelled" || r.status === "failed"
                              ? "bg-red-900/40 text-red-200"
                              : "bg-amber-900/40 text-amber-200")
                        }
                      >
                        {r.status}
                      </span>
                      {r.started_by ? (
                        <span className="ml-2">by {r.started_by}</span>
                      ) : null}
                      {r.started_at ? (
                        <span className="ml-2">
                          · {new Date(r.started_at).toLocaleString()}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">
                    id={r.id}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}