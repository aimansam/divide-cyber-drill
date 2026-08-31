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
 * Q21 & UX Improvements:
 *   * Live auto-refresh polling every 2.5s when isLive or active.
 *   * Relative vs exact ISO timestamp toggle.
 *   * Action family filter chips ("all", "run.*", "asset.*", "flag.*", "error").
 *   * Quick search filter across action, actor, and JSON details.
 *   * Actor filter dropdown.
 *   * Copy details JSON to clipboard button with visual feedback.
 *   * Export audit log as JSON.
 *   * Click-to-expand details disclosure.
 *   * Empty ``{}`` details are hidden.
 *   * Null actor renders as ``system``.
 *   * Compact mode (used inside DrillConsole) keeps a small
 *     ``run #NN`` chip in the header so operators know what
 *     they're looking at without scrolling back up.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Download,
  Loader2,
  Radio,
  RefreshCw,
  ScrollText,
  Search,
} from "lucide-react";
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

export interface AuditRow {
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
const ACTION_TONES: Record<string, string> = {
  "scenario.created": "bg-emerald-900/40 text-emerald-200 border-emerald-700/50",
  "scenario.updated": "bg-emerald-900/40 text-emerald-200 border-emerald-700/50",
  "scenario.deleted": "bg-red-900/40 text-red-200 border-red-700/50",
  "run.started": "bg-emerald-900/40 text-emerald-200 border-emerald-700/50",
  "run.completed": "bg-emerald-900/40 text-emerald-200 border-emerald-700/50",
  "run.cancelled": "bg-amber-900/40 text-amber-200 border-amber-700/50",
  "run.stopped": "bg-amber-900/40 text-amber-200 border-amber-700/50",
  "run.failed": "bg-red-900/40 text-red-200 border-red-700/50",
  "run.timeout": "bg-red-900/40 text-red-200 border-red-700/50",
  "asset.spawned": "bg-sky-900/40 text-sky-200 border-sky-700/50",
  "asset.orphaned": "bg-orange-900/40 text-orange-200 border-orange-700/50",
  "asset.failed": "bg-red-900/40 text-red-200 border-red-700/50",
  "flag.planted": "bg-violet-900/40 text-violet-200 border-violet-700/50",
  "password.reset.issued": "bg-zinc-700/40 text-zinc-200 border-zinc-600/50",
  "password.reset.used": "bg-zinc-700/40 text-zinc-200 border-zinc-600/50",
};

export function tone(action: string | undefined): string {
  if (!action) return "bg-zinc-700/40 text-zinc-200 border-zinc-700";
  return ACTION_TONES[action] ?? "bg-zinc-700/40 text-zinc-200 border-zinc-700";
}

export function actionLabel(action: string | undefined): string {
  if (!action) return "?";
  return action
    .split(".")
    .map((seg) => seg.toUpperCase().replace(/_/g, " "))
    .join(" · ");
}

export function relativeTime(iso: string | null | undefined): string {
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

export function exactTime(iso: string | null | undefined): string {
  if (!iso) return "?";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "?";
  return d.toLocaleTimeString([], { hour12: false }) + `.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

export function hasDetails(details: unknown): boolean {
  if (details === null || details === undefined) return false;
  if (typeof details !== "object") return Boolean(details);
  return Object.keys(details as Record<string, unknown>).length > 0;
}

export function AuditExplorerCard({
  pickedRunId,
  compact = false,
  isLive = false,
  onLatestEvent,
}: {
  pickedRunId: number | null;
  compact?: boolean;
  isLive?: boolean;
  onLatestEvent?: (latest: AuditRow | null) => void;
}) {
  const [items, setItems] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionFilter, setActionFilter] = useState<"all" | "run" | "asset" | "flag" | "error" | "system">("all");
  const [actorFilter, setActorFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [showExactTime, setShowExactTime] = useState<boolean>(false);
  const [copiedId, setCopiedId] = useState<string | number | null>(null);
  const [expandedId, setExpandedId] = useState<number | string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load(silent = false) {
    if (pickedRunId === null) {
      setItems([]);
      setError(null);
      if (onLatestEvent) onLatestEvent(null);
      return;
    }
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await api.get<AuditPayload>(
        `/api/v1/drills/${pickedRunId}/audit`,
      );
      const rows = data.items ?? [];
      setItems(rows);
      if (onLatestEvent) {
        onLatestEvent(rows.length > 0 ? rows[rows.length - 1] : null);
      }
    } catch (e: unknown) {
      if (!silent) {
        setError(detailFromError(e));
        setItems([]);
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedRunId]);

  // Live polling: refresh audit events every 2.5s if isLive is true
  useEffect(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    if (pickedRunId !== null && isLive) {
      pollTimerRef.current = setInterval(() => {
        void load(true);
      }, 2500);
    }

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedRunId, isLive]);

  // Unique list of actors from the loaded rows
  const uniqueActors = useMemo(() => {
    const set = new Set<string>();
    items.forEach((r) => set.add(r.actor || "system"));
    return Array.from(set).sort();
  }, [items]);

  // Filtered rows based on category, actor, and text search
  const filteredItems = useMemo(() => {
    return items.filter((row) => {
      const act = row.action ?? "";
      const actorName = row.actor || "system";

      // Category filter
      if (actionFilter === "run" && !act.startsWith("run.")) return false;
      if (actionFilter === "asset" && !act.startsWith("asset.")) return false;
      if (actionFilter === "flag" && !act.startsWith("flag.")) return false;
      if (actionFilter === "system" && !act.startsWith("password.")) return false;
      if (actionFilter === "error") {
        const isErr =
          act.endsWith(".failed") ||
          act.endsWith(".timeout") ||
          act.endsWith(".orphaned") ||
          act.endsWith(".cancelled");
        if (!isErr) return false;
      }

      // Actor filter
      if (actorFilter !== "all" && actorFilter !== actorName) return false;

      // Text query filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const detailsStr = row.details ? JSON.stringify(row.details).toLowerCase() : "";
        const matchAction = act.toLowerCase().includes(q);
        const matchActor = actorName.toLowerCase().includes(q);
        const matchAsset = row.asset_id !== null && row.asset_id !== undefined && String(row.asset_id).includes(q);
        const matchDetails = detailsStr.includes(q);
        if (!matchAction && !matchActor && !matchAsset && !matchDetails) {
          return false;
        }
      }

      return true;
    });
  }, [items, actionFilter, actorFilter, searchQuery]);

  function copyDetailsJson(id: string | number, details: unknown) {
    if (!details) return;
    navigator.clipboard.writeText(JSON.stringify(details, null, 2));
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  function exportAuditJson() {
    if (items.length === 0 || pickedRunId === null) return;
    const blob = new Blob([JSON.stringify(items, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `drill-run-${pickedRunId}-audit.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const errorCount = useMemo(() => {
    return items.filter((r) => {
      const act = r.action ?? "";
      return (
        act.endsWith(".failed") ||
        act.endsWith(".timeout") ||
        act.endsWith(".orphaned") ||
        act.endsWith(".cancelled")
      );
    }).length;
  }, [items]);

  return (
    <Card>
      {!compact ? (
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <div>
            <CardTitle>
              <span className="inline-flex items-center gap-2">
                <ScrollText className="h-4 w-4 text-muted-foreground" />
                Audit log
                {isLive && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
                    <Radio className="h-3 w-3 animate-pulse text-emerald-400" />
                    Live
                  </span>
                )}
              </span>
            </CardTitle>
            <CardDescription>
              {pickedRunId === null
                ? "Click a run to read its audit timeline."
                : `Run #${pickedRunId} — ${filteredItems.length} of ${items.length} event${items.length === 1 ? "" : "s"}${
                    errorCount > 0 ? ` (${errorCount} warning/error${errorCount === 1 ? "" : "s"})` : ""
                  }`}
            </CardDescription>
          </div>
          <div className="flex items-center gap-1.5">
            {items.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={exportAuditJson}
                title="Export audit timeline as JSON"
                className="h-8 text-xs"
              >
                <Download className="mr-1 h-3.5 w-3.5" />
                Export
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => load(false)}
              aria-label="Refresh"
              disabled={pickedRunId === null || loading}
              className="h-8 w-8"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
          </div>
        </CardHeader>
      ) : (
        <div className="flex items-center justify-between border-b border-border/50 px-4 py-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>
              {pickedRunId !== null ? `Run #${pickedRunId}` : "No run selected"} ·{" "}
              {filteredItems.length} of {items.length} events
            </span>
            {isLive && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-1.5 py-0.2 text-[10px] font-medium text-emerald-400">
                <Radio className="h-2.5 w-2.5 animate-pulse text-emerald-400" />
                live
              </span>
            )}
            {errorCount > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded bg-red-950/60 px-1.5 py-0.5 text-[10px] font-medium text-red-300">
                <AlertTriangle className="h-2.5 w-2.5" />
                {errorCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {items.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                onClick={exportAuditJson}
                title="Export JSON"
                className="h-6 w-6"
              >
                <Download className="h-3 w-3" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => load(false)}
              disabled={pickedRunId === null || loading}
              className="h-6 w-6"
              title="Refresh audit"
            >
              {loading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
            </Button>
          </div>
        </div>
      )}

      <CardContent className={compact ? "pt-3" : "pt-2"}>
        {error && (
          <div className="rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        )}

        {!error && !loading && pickedRunId === null && (
          <div className="py-4 text-center text-sm italic text-muted-foreground">
            No run selected.
          </div>
        )}

        {!error && !loading && pickedRunId !== null && items.length === 0 && (
          <div className="py-4 text-center text-sm italic text-muted-foreground">
            No audit events yet. The run.started event should appear here within a second of starting.
          </div>
        )}

        {!error && items.length > 0 && (
          <div className="mb-3 space-y-2">
            {/* Filter toolbar: Search + Category chips + Actor select + Time format */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div
                className="flex flex-wrap items-center gap-1"
                data-testid="audit-filter"
                role="radiogroup"
                aria-label="Filter by action family"
              >
                {(
                  [
                    { id: "all", label: "All" },
                    { id: "run", label: "Run" },
                    { id: "asset", label: "Asset" },
                    { id: "flag", label: "Flags" },
                    { id: "error", label: `Errors${errorCount > 0 ? ` (${errorCount})` : ""}` },
                    { id: "system", label: "System" },
                  ] as const
                ).map(({ id, label }) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={actionFilter === id}
                    onClick={() => setActionFilter(id)}
                    className={
                      "rounded-md border px-2 py-0.5 text-xs font-medium uppercase tracking-wide transition-colors " +
                      (actionFilter === id
                        ? id === "error"
                          ? "border-red-500 bg-red-500/20 text-red-300"
                          : "border-primary bg-primary/20 text-primary"
                        : "border-border bg-card/40 text-muted-foreground hover:bg-accent")
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                {uniqueActors.length > 1 && (
                  <select
                    value={actorFilter}
                    onChange={(e) => setActorFilter(e.target.value)}
                    className="h-7 rounded border border-border bg-background px-2 text-xs text-foreground focus:outline-none"
                    aria-label="Filter by actor"
                  >
                    <option value="all">All actors</option>
                    {uniqueActors.map((actor) => (
                      <option key={actor} value={actor}>
                        {actor}
                      </option>
                    ))}
                  </select>
                )}

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowExactTime(!showExactTime)}
                  className="h-7 px-2 text-[11px] text-muted-foreground hover:text-foreground"
                  title={showExactTime ? "Switch to relative time (e.g. 2m ago)" : "Switch to exact timestamp"}
                >
                  <Clock className="mr-1 h-3 w-3" />
                  {showExactTime ? "Exact" : "Relative"}
                </Button>
              </div>
            </div>

            {/* Quick search input */}
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search audit action, actor, or payload details…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-7 pl-8 text-xs"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2 top-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  ✕
                </button>
              )}
            </div>
          </div>
        )}

        <ol className="space-y-1">
          {filteredItems.map((row, i) => {
            const rowKey = row.id ?? `${row.at}-${i}`;
            const expanded = expandedId === rowKey;
            const showDetails = hasDetails(row.details);
            const actorLabel = row.actor ?? "system";
            const isCopied = copiedId === rowKey;

            return (
              <li
                key={rowKey}
                className="overflow-hidden rounded border border-border/80 bg-card/30 text-xs transition-colors"
                data-testid="audit-row"
              >
                <div className="flex w-full items-center justify-between">
                  <button
                    type="button"
                    onClick={() => showDetails && setExpandedId(expanded ? null : rowKey)}
                    aria-expanded={expanded}
                    className={
                      "flex min-w-0 flex-1 items-start gap-2 px-2 py-1.5 text-left " +
                      (showDetails ? "cursor-pointer hover:bg-accent/40" : "cursor-default")
                    }
                  >
                    {showDetails ? (
                      expanded ? (
                        <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )
                    ) : (
                      <span className="mt-0.5 inline-block h-3.5 w-3.5 shrink-0" />
                    )}

                    <span
                      className={`inline-block shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${tone(
                        row.action,
                      )}`}
                      title={row.action ?? ""}
                    >
                      {actionLabel(row.action)}
                    </span>

                    <span
                      className="shrink-0 font-mono text-[11px] text-muted-foreground"
                      title={row.at ?? ""}
                    >
                      {showExactTime ? exactTime(row.at) : relativeTime(row.at)}
                    </span>

                    <span className="shrink-0 rounded bg-muted/40 px-1 py-0.2 font-mono text-[11px] text-foreground/90">
                      {actorLabel}
                    </span>

                    {row.asset_id !== null && row.asset_id !== undefined ? (
                      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                        asset={row.asset_id}
                      </span>
                    ) : null}

                    {showDetails && !expanded ? (
                      <span className="ml-auto truncate font-mono text-[11px] text-muted-foreground">
                        {JSON.stringify(row.details)}
                      </span>
                    ) : null}
                  </button>

                  {showDetails && expanded && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => copyDetailsJson(rowKey, row.details)}
                      className="mr-2 h-6 px-2 text-[10px] text-muted-foreground hover:text-foreground"
                      title="Copy JSON details"
                    >
                      {isCopied ? (
                        <>
                          <Check className="mr-1 h-3 w-3 text-emerald-400" />
                          Copied
                        </>
                      ) : (
                        <>
                          <Copy className="mr-1 h-3 w-3" />
                          Copy JSON
                        </>
                      )}
                    </Button>
                  )}
                </div>

                {expanded && showDetails && (
                  <div className="relative border-t border-border bg-background/80 px-3 py-2">
                    <pre
                      className="overflow-x-auto text-[11px] font-mono leading-relaxed text-foreground/90"
                      data-testid="audit-row-details"
                    >
                      {JSON.stringify(row.details, null, 2)}
                    </pre>
                  </div>
                )}
              </li>
            );
          })}
        </ol>

        {!error && !loading && items.length > 0 && filteredItems.length === 0 && (
          <div className="mt-3 rounded border border-dashed border-border p-3 text-center text-xs italic text-muted-foreground">
            No events match the current search or filters.{" "}
            <button
              type="button"
              className="font-medium underline hover:text-foreground"
              onClick={() => {
                setActionFilter("all");
                setActorFilter("all");
                setSearchQuery("");
              }}
            >
              Reset filters
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
