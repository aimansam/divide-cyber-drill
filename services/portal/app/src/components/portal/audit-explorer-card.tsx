/**
 * AuditExplorerCard — append-only audit timeline for the picked run.
 *
 * Drives off `pickedRunId`. We fetch `GET /api/v1/drills/{id}/audit`
 * (visibility-filtered server-side; commit 4d840f9).
 *
 * Roles (M3.2, Half 2): shown to everyone. The server returns
 * 403 if a red/blue caller tries to read an audit that isn't
 * theirs; the card surfaces that as a destructive error. Admin,
 * lead, observer see every audit.
 *
 * Format: oldest-first timeline (matches the API response). Each
 * row carries `at` (ISO), `action` (e.g. `RUN_STARTED`,
 * `ASSET_SPAWNED`, `RUN_COMPLETED`, `RUN_CANCELLED`, `RUN_FAILED`),
 * `actor` (token subject — usually `req.started_by` for the run's
 * own events, `meSub` for cancel events, the watchdog for
 * auto-timeout events once next-plan #4 lands), and an optional
 * `details` JSON blob.
 */

import { useEffect, useState } from "react";
import { Loader2, RefreshCw, ScrollText } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";

interface AuditRow {
  id?: number;
  at?: string | null;
  action?: string;
  actor?: string | null;
  scenario_id?: number | null;
  asset_id?: number | null;
  details?: Record<string, unknown> | null;
}

interface AuditPayload {
  items?: AuditRow[];
  total?: number;
}

const ACTION_TONES: Record<string, string> = {
  RUN_STARTED: "bg-emerald-900/40 text-emerald-200",
  RUN_COMPLETED: "bg-emerald-900/40 text-emerald-200",
  RUN_CANCELLED: "bg-amber-900/40 text-amber-200",
  RUN_CANCELED: "bg-amber-900/40 text-amber-200",
  RUN_FAILED: "bg-red-900/40 text-red-200",
  RUN_TIMEOUT: "bg-red-900/40 text-red-200",
  ASSET_SPAWNED: "bg-sky-900/40 text-sky-200",
  ASSET_READY: "bg-sky-900/40 text-sky-200",
  ASSET_TERMINATED: "bg-zinc-700/40 text-zinc-200",
};

function tone(action: string | undefined): string {
  if (!action) return "bg-zinc-700/40 text-zinc-200";
  return ACTION_TONES[action] ?? "bg-zinc-700/40 text-zinc-200";
}

export function AuditExplorerCard({
  pickedRunId,
}: {
  pickedRunId: number | null;
}) {
  const [items, setItems] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (pickedRunId === null) {
      setItems([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<AuditPayload>(
        `/api/v1/drills/${pickedRunId}/audit`,
      );
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
    // pickedRunId change -> re-fetch.
  }, [pickedRunId]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <ScrollText className="h-4 w-4 text-muted-foreground" />
              Audit log
            </span>
          </CardTitle>
          <CardDescription>
            {pickedRunId === null
              ? "Click a run to read its audit timeline."
              : `Run #${pickedRunId} — ${items.length} event${items.length === 1 ? "" : "s"}`}
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
        {!error && !loading && pickedRunId === null && (
          <div className="text-sm italic text-muted-foreground">
            No run selected.
          </div>
        )}
        {!error && !loading && pickedRunId !== null && items.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            No audit events yet. The run.started event should appear
            here within a second of starting.
          </div>
        )}
        <ol className="space-y-1">
          {items.map((row, i) => (
            <li
              key={row.id ?? `${row.at}-${i}`}
              className="flex items-start gap-2 rounded border border-border bg-card/30 px-2 py-1 text-xs"
            >
              <span
                className={`inline-block shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] ${tone(row.action)}`}
              >
                {row.action ?? "?"}
              </span>
              <span className="font-mono text-muted-foreground">
                {row.at ? new Date(row.at).toLocaleString() : "?"}
              </span>
              <span className="font-mono">
                {row.actor ?? "?"}
              </span>
              {row.asset_id !== null && row.asset_id !== undefined ? (
                <span className="font-mono text-muted-foreground">
                  asset={row.asset_id}
                </span>
              ) : null}
              {row.details ? (
                <span className="ml-auto truncate font-mono text-muted-foreground">
                  {JSON.stringify(row.details)}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}