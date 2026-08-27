/**
 * GlobalAuditCard -- cross-run audit search.
 *
 * Mounted on the Admin tab (alongside OperatorConsoleCard etc).
 * Lets admins/leads/observers search the entire audit log across
 * every run, every actor, every time window. Reuses the same
 * row-rendering helpers from AuditExplorerCard so the look &
 * feel stays consistent.
 *
 * Filters (Q21):
 *   * action:  substring match (e.g. "run.failed" matches "run.failed")
 *   * actor:   exact match (e.g. "admin", "system" for null actor)
 *   * run_id:  exact match
 *   * since:   ISO datetime lower bound
 *   * until:   ISO datetime upper bound
 *   * limit:   default 200, capped at 1000
 *
 * RBAC: admin, lead, observer. Red/blue get a 403.
 */
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RefreshCw, ScrollText } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, detailFromError } from "@/lib/api";

interface AuditRow {
  id?: number;
  at?: string | null;
  action?: string;
  actor?: string | null;
  scenario_id?: number | null;
  asset_id?: number | null;
  run_id?: number | null;
  details?: Record<string, unknown> | null;
}

interface AuditPayload {
  items?: AuditRow[];
  total?: number;
  limit?: number;
}

// Reuse the action tones from the per-run audit card by inlining
// a copy. Keeping it here avoids a cross-card import + circular
// dependency between audit-explorer-card and global-audit-card.
const ACTION_TONES: Record<string, string> = {
  "scenario.created": "bg-emerald-900/40 text-emerald-200",
  "scenario.updated": "bg-emerald-900/40 text-emerald-200",
  "scenario.deleted": "bg-red-900/40 text-red-200",
  "run.started": "bg-emerald-900/40 text-emerald-200",
  "run.completed": "bg-emerald-900/40 text-emerald-200",
  "run.cancelled": "bg-amber-900/40 text-amber-200",
  "run.stopped": "bg-amber-900/40 text-amber-200",
  "run.failed": "bg-red-900/40 text-red-200",
  "run.timeout": "bg-red-900/40 text-red-200",
  "asset.spawned": "bg-sky-900/40 text-sky-200",
  "asset.orphaned": "bg-orange-900/40 text-orange-200",
  "asset.failed": "bg-red-900/40 text-red-200",
  "flag.planted": "bg-violet-900/40 text-violet-200",
  "password.reset.issued": "bg-zinc-700/40 text-zinc-200",
  "password.reset.used": "bg-zinc-700/40 text-zinc-200",
};

function tone(action: string | undefined): string {
  if (!action) return "bg-zinc-700/40 text-zinc-200";
  return ACTION_TONES[action] ?? "bg-zinc-700/40 text-zinc-200";
}

function actionLabel(action: string | undefined): string {
  if (!action) return "?";
  return action
    .split(".")
    .map((seg) => seg.toUpperCase().replace(/_/g, " "))
    .join(" · ");
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "?";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "?";
  const diff = Date.now() - t;
  if (diff < 0) return new Date(iso).toLocaleString();
  if (diff < 5_000) return "just now";
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return new Date(iso).toLocaleString();
}

function hasDetails(details: unknown): boolean {
  if (details === null || details === undefined) return false;
  if (typeof details !== "object") return Boolean(details);
  return Object.keys(details as Record<string, unknown>).length > 0;
}

export function GlobalAuditCard() {
  const [items, setItems] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<number | string | null>(null);
  // Filter inputs -- controlled so the user can type without
  // firing a fetch on every keystroke. The "Apply" button
  // commits the filter and triggers load().
  const [filterAction, setFilterAction] = useState("");
  const [filterActor, setFilterActor] = useState("");
  const [filterRunId, setFilterRunId] = useState("");
  const [filterSince, setFilterSince] = useState("");
  // Committed filters -- only used by load().
  const [committed, setCommitted] = useState({
    action: "",
    actor: "",
    run_id: "",
    since: "",
  });

  function buildUrl(): string {
    const params = new URLSearchParams();
    if (committed.action) params.set("action", committed.action);
    if (committed.actor) params.set("actor", committed.actor);
    if (committed.run_id) params.set("run_id", committed.run_id);
    if (committed.since) params.set("since", committed.since);
    params.set("limit", "200");
    const qs = params.toString();
    return qs ? `/api/v1/audit?${qs}` : "/api/v1/audit?limit=200";
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<AuditPayload>(buildUrl());
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
    // Re-fetch when committed filters change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed]);

  function applyFilters() {
    setCommitted({
      action: filterAction.trim(),
      actor: filterActor.trim(),
      run_id: filterRunId.trim(),
      since: filterSince.trim(),
    });
  }

  function resetFilters() {
    setFilterAction("");
    setFilterActor("");
    setFilterRunId("");
    setFilterSince("");
    setCommitted({ action: "", actor: "", run_id: "", since: "" });
  }

  return (
    <Card data-testid="global-audit-card">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>
            <span className="inline-flex items-center gap-2">
              <ScrollText className="h-4 w-4 text-muted-foreground" />
              Global audit log
            </span>
          </CardTitle>
          <CardDescription>
            Search every audit row across every run. Showing the{" "}
            {items.length} most recent event{items.length === 1 ? "" : "s"}.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={load}
          aria-label="Refresh"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </CardHeader>
      <CardContent>
        {/* Filter inputs */}
        <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            placeholder="action (e.g. run.failed)"
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
            className="font-mono text-xs"
            data-testid="global-audit-action"
          />
          <Input
            placeholder="actor (e.g. admin)"
            value={filterActor}
            onChange={(e) => setFilterActor(e.target.value)}
            className="font-mono text-xs"
            data-testid="global-audit-actor"
          />
          <Input
            placeholder="run_id (numeric)"
            value={filterRunId}
            onChange={(e) => setFilterRunId(e.target.value)}
            className="font-mono text-xs"
            data-testid="global-audit-run-id"
          />
          <Input
            type="datetime-local"
            value={filterSince}
            onChange={(e) => setFilterSince(e.target.value)}
            className="font-mono text-xs"
            data-testid="global-audit-since"
            title="Lower bound on event timestamp"
          />
        </div>
        <div className="mb-3 flex items-center gap-2">
          <Button size="sm" onClick={applyFilters} data-testid="global-audit-apply">
            Apply filters
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={resetFilters}
            data-testid="global-audit-reset"
          >
            Reset
          </Button>
        </div>

        {error && (
          <div className="text-sm text-destructive">{error}</div>
        )}
        {!error && !loading && items.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            No audit events match these filters.
          </div>
        )}
        <ol className="space-y-1">
          {items.map((row, i) => {
            const rowKey = row.id ?? `${row.at}-${i}`;
            const expanded = expandedId === rowKey;
            const showDetails = hasDetails(row.details);
            const actorLabel = row.actor ?? "system";
            return (
              <li
                key={rowKey}
                className="rounded border border-border bg-card/30 text-xs"
                data-testid="global-audit-row"
              >
                <button
                  type="button"
                  onClick={() => showDetails && setExpandedId(expanded ? null : rowKey)}
                  aria-expanded={expanded}
                  className={
                    "flex w-full items-start gap-2 px-2 py-1 text-left " +
                    (showDetails ? "cursor-pointer hover:bg-accent/40" : "cursor-default")
                  }
                >
                  {showDetails ? (
                    expanded ? (
                      <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                    )
                  ) : (
                    <span className="mt-0.5 inline-block h-3 w-3 shrink-0" />
                  )}
                  <span
                    className={`inline-block shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] ${tone(row.action)}`}
                    title={row.action ?? ""}
                  >
                    {actionLabel(row.action)}
                  </span>
                  <span
                    className="font-mono text-muted-foreground"
                    title={row.at ?? ""}
                  >
                    {relativeTime(row.at)}
                  </span>
                  <span className="font-mono">{actorLabel}</span>
                  {row.run_id !== null && row.run_id !== undefined ? (
                    <span className="font-mono text-muted-foreground">
                      run=#{row.run_id}
                    </span>
                  ) : null}
                  {showDetails && !expanded ? (
                    <span className="ml-auto truncate font-mono text-muted-foreground">
                      {JSON.stringify(row.details)}
                    </span>
                  ) : null}
                </button>
                {expanded && showDetails && (
                  <pre
                    className="overflow-x-auto border-t border-border bg-background/60 px-3 py-2 text-[11px] font-mono text-foreground/80"
                    data-testid="global-audit-row-details"
                  >
                    {JSON.stringify(row.details, null, 2)}
                  </pre>
                )}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
