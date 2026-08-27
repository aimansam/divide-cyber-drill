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
 *
 * Q21 polish:
 *   * Relative timestamps ("2m ago") in the timestamp column.
 *   * Action filter chips ("all", "run.*", "asset.*", "system.*").
 *   * Click-to-expand details disclosure -- inline JSON.stringify
 *     is replaced by a panel that opens on click.
 *   * Empty ``{}`` details are hidden.
 *   * Null actor renders as ``system`` instead of ``?`` so the
 *     operator can tell "no actor" from "load failed".
 *   * Compact mode (used inside DrillConsole) keeps a small
 *     ``run #NN`` chip in the header so operators know what
 *     they're looking at without scrolling back up.
 */

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RefreshCw, ScrollText } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, detailFromError } from "@/lib/api";

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

// Q18: keys match the wire shape — the API serialises the
// AuditAction enum as lowercase dotted strings (e.g. ``run.started``).
// Pre-Q18 the keys were uppercase enum-names (``RUN_STARTED``) which
// never matched anything returned by the API, so every audit row
// fell through to the default ``bg-zinc-700/40`` tone. Every row
// looked identical. Switched to the wire shape AND extended the
// set with ``run.stopped`` (added by Q17) and ``asset.orphaned``
// (added by Q14).
const ACTION_TONES: Record<string, string> = {
  "scenario.created": "bg-emerald-900/40 text-emerald-200",
  "scenario.updated": "bg-emerald-900/40 text-emerald-200",
  "scenario.deleted": "bg-red-900/40 text-red-200",
  "run.started": "bg-emerald-900/40 text-emerald-200",
  "run.completed": "bg-emerald-900/40 text-emerald-200",
  "run.cancelled": "bg-amber-900/40 text-amber-200",
  "run.stopped": "bg-amber-900/40 text-amber-200", // Q17: operator-initiated
  "run.failed": "bg-red-900/40 text-red-200",
  "run.timeout": "bg-red-900/40 text-red-200",
  "asset.spawned": "bg-sky-900/40 text-sky-200",
  "asset.orphaned": "bg-orange-900/40 text-orange-200", // Q14: post-drill cleanup failure
  "asset.failed": "bg-red-900/40 text-red-200",
  "flag.planted": "bg-violet-900/40 text-violet-200",
  "password.reset.issued": "bg-zinc-700/40 text-zinc-200",
  "password.reset.used": "bg-zinc-700/40 text-zinc-200",
};

function tone(action: string | undefined): string {
  if (!action) return "bg-zinc-700/40 text-zinc-200";
  return ACTION_TONES[action] ?? "bg-zinc-700/40 text-zinc-200";
}

/**
 * Q18: render audit actions in a more readable form. The wire
 * shape is lowercase dotted (``run.stopped``); we display the
 * uppercase enum-style label (``RUN STOPPED``) but keep the
 * original string as a hover tooltip so power users can still
 * grep by the API shape.
 */
function actionLabel(action: string | undefined): string {
  if (!action) return "?";
  return action
    .split(".")
    .map((seg) => seg.toUpperCase().replace(/_/g, " "))
    .join(" · ");
}

/**
 * Q21: relative timestamp for at-a-glance scanning. Falls back
 * to the locale string for events far in the past or future.
 * Examples: "just now", "12s ago", "3m ago", "2h ago".
 */
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

/**
 * Q21: details payload has lots of empty objects. Treat
 * ``{}``, ``[]``, and ``null`` as "no details" so we don't
 * render an ugly chip.
 */
function hasDetails(details: unknown): boolean {
  if (details === null || details === undefined) return false;
  if (typeof details !== "object") return Boolean(details);
  return Object.keys(details as Record<string, unknown>).length > 0;
}

export function AuditExplorerCard({
  pickedRunId,
  compact = false,
}: {
  pickedRunId: number | null;
  compact?: boolean;
}) {
  const [items, setItems] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /**
   * Q21: filter by action family. ``"all"`` shows everything;
   * ``"run"`` matches ``run.started``, ``run.stopped`` etc;
   * ``"asset"`` matches ``asset.spawned`` etc; ``"system"``
   * matches the password-reset events. Defaults to ``"all"``
   * to preserve the pre-Q21 behaviour.
   */
  const [actionFilter, setActionFilter] = useState<"all" | "run" | "asset" | "system">("all");
  /**
   * Q21: which row is expanded to show its ``details`` blob.
   * Only one row is expanded at a time (click another to switch).
   * Models a disclosure pattern common to audit-log UIs.
   */
  const [expandedId, setExpandedId] = useState<number | string | null>(null);

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
      setError(detailFromError(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // pickedRunId change -> re-fetch.
  }, [pickedRunId]);

  /**
   * Q21: filter the loaded items by the selected action family.
   * Done in a memo so re-renders triggered by ``expandedId`` or
   * ``actionFilter`` don't walk the list more than necessary.
   */
  const filteredItems = useMemo(() => {
    if (actionFilter === "all") return items;
    return items.filter((row) => (row.action ?? "").startsWith(`${actionFilter}.`));
  }, [items, actionFilter]);

  return (
    <Card>
      {!compact && (
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
              : `Run #${pickedRunId} — ${filteredItems.length} of ${items.length} event${items.length === 1 ? "" : "s"}`}
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
      )}
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
        {!error && items.length > 0 && (
          /* Q21: filter chips. Cheap radio-style segmented control
             that scopes which rows render below. */
          <div
            className="mb-2 flex flex-wrap items-center gap-1"
            data-testid="audit-filter"
            role="radiogroup"
            aria-label="Filter by action family"
          >
            {(["all", "run", "asset", "system"] as const).map((opt) => (
              <button
                key={opt}
                type="button"
                role="radio"
                aria-checked={actionFilter === opt}
                onClick={() => setActionFilter(opt)}
                className={
                  "rounded-md border px-2 py-0.5 text-xs font-medium uppercase tracking-wide transition-colors " +
                  (actionFilter === opt
                    ? "border-primary bg-primary/20 text-primary"
                    : "border-border bg-card/40 text-muted-foreground hover:bg-accent")
                }
              >
                {opt}
              </button>
            ))}
          </div>
        )}
        <ol className="space-y-1">
          {filteredItems.map((row, i) => {
            const rowKey = row.id ?? `${row.at}-${i}`;
            const expanded = expandedId === rowKey;
            const showDetails = hasDetails(row.details);
            const actorLabel = row.actor ?? "system";
            return (
              <li
                key={rowKey}
                className="rounded border border-border bg-card/30 text-xs"
                data-testid="audit-row"
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
                  {row.asset_id !== null && row.asset_id !== undefined ? (
                    <span className="font-mono text-muted-foreground">
                      asset={row.asset_id}
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
                    data-testid="audit-row-details"
                  >
                    {JSON.stringify(row.details, null, 2)}
                  </pre>
                )}
              </li>
            );
          })}
        </ol>
        {!error && !loading && items.length > 0 && filteredItems.length === 0 && (
          <div className="mt-2 text-xs italic text-muted-foreground">
            No events match the {actionFilter} filter.{" "}
            <button
              type="button"
              className="underline hover:text-foreground"
              onClick={() => setActionFilter("all")}
            >
              Clear filter
            </button>
            .
          </div>
        )}
      </CardContent>
    </Card>
  );
}