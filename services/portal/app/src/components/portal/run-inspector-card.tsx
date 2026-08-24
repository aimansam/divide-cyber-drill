/**
 * RunInspectorCard — full detail of one picked run.
 *
 * Drives off `pickedRunId`. Fetches `GET /api/v1/drills/{id}`
 * (visibility-filtered server-side; commit 4d840f9) and renders
 * every field the API returns: status, started_by, started_at,
 * ended_at, duration_sec, error, and the assets list.
 *
 * Roles: shown to admin/lead/red/blue/observer (everyone with a
 * verified identity). Server-side, the endpoint enforces
 * `can_view_run` — a red/blue caller looking at someone else's
 * run gets 403, which surfaces here as a destructive error.
 *
 * `RunLifecycleCard` keeps its own (less complete) run detail
 * because it also owns the start/refresh/cancel workflow and
 * polls every 2s. Splitting the polling lifecycle from the
 * read-only detail keeps both cards simple.
 */

import { useEffect, useState } from "react";
import { Loader2, RefreshCw, Search } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type { RunDetail } from "@/components/portal/run-lifecycle-card";

export function RunInspectorCard({
  pickedRunId,
}: {
  pickedRunId: number | null;
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (pickedRunId === null) {
      setRun(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<RunDetail>(`/api/v1/drills/${pickedRunId}`);
      setRun(data);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? `HTTP ${e.status} ${e.url}` : String(e);
      setError(msg);
      setRun(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // pickedRunId change -> re-fetch. The lifecycle card handles
    // the 2s polling for live status; this card is a manual refresh.
  }, [pickedRunId]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              Run inspector
            </span>
          </CardTitle>
          <CardDescription>
            {pickedRunId === null
              ? "Click a run in My runs / All runs to inspect it."
              : `Run #${pickedRunId}`}
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={load}
          aria-label="Refresh"
          disabled={pickedRunId === null}
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
          <div className="text-sm text-destructive">{error}</div>
        )}
        {!error && !loading && run === null && pickedRunId !== null && (
          <div className="text-sm italic text-muted-foreground">
            No data.
          </div>
        )}
        {!error && !loading && run === null && pickedRunId === null && (
          <div className="text-sm italic text-muted-foreground">
            No run selected.
          </div>
        )}
        {run !== null && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">status</dt>
            <dd className="font-mono">{run.status}</dd>
            <dt className="text-muted-foreground">scenario</dt>
            <dd className="font-mono">{run.scenario_id ?? "—"}</dd>
            <dt className="text-muted-foreground">started_by</dt>
            <dd className="font-mono">{run.started_by ?? "—"}</dd>
            <dt className="text-muted-foreground">started_at</dt>
            <dd className="font-mono">
              {run.started_at
                ? new Date(run.started_at).toLocaleString()
                : "—"}
            </dd>
            <dt className="text-muted-foreground">ended_at</dt>
            <dd className="font-mono">
              {run.ended_at ? new Date(run.ended_at).toLocaleString() : "—"}
            </dd>
            <dt className="text-muted-foreground">duration</dt>
            <dd className="font-mono">
              {run.duration_sec !== null && run.duration_sec !== undefined
                ? `${Math.round(run.duration_sec)}s`
                : "—"}
            </dd>
            {run.error ? (
              <>
                <dt className="text-muted-foreground">error</dt>
                <dd className="font-mono text-destructive">{run.error}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">assets</dt>
            <dd className="font-mono">
              {run.assets?.length ?? 0}
              {run.assets && run.assets.length > 0
                ? ` — ${run.assets
                    .map(
                      (a) =>
                        `${a.role ?? a.kind ?? "?"}${a.pve_vmid !== null && a.pve_vmid !== undefined ? `(vmid=${a.pve_vmid})` : ""}${a.pve_ip ? `(${a.pve_ip})` : ""}`,
                    )
                    .join(", ")}`
                : ""}
            </dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}