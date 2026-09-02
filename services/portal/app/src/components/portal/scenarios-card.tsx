import { useEffect, useMemo, useState } from "react";
import {
  Loader2,
  RefreshCw,
  Search,
  X,
  Target,
  Clock,
  TrendingUp,
  Shield,
  Zap,
  Skull,
  ChevronRight,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, detailFromError } from "@/lib/api";

export interface Scenario {
  id: number;
  name: string;
  title?: string;
  version?: number;
  difficulty?: string;
  duration_min?: number;
  run_count?: number;
}

interface ScenariosPayload {
  items?: Scenario[];
  total?: number;
}

const DIFFICULTY_CONFIG: Record<
  string,
  { badge: string; icon: React.ReactNode; label: string }
> = {
  beginner: {
    badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    icon: <Shield className="h-3 w-3" />,
    label: "Beginner",
  },
  intermediate: {
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    icon: <Zap className="h-3 w-3" />,
    label: "Intermediate",
  },
  advanced: {
    badge: "bg-red-500/10 text-red-400 border-red-500/20",
    icon: <Skull className="h-3 w-3" />,
    label: "Advanced",
  },
};

/**
 * ScenariosCard — compact, high-density catalog sidebar for the Operate view.
 *
 * Provides instant filtering, active state indication, and metadata badges.
 */
export function ScenariosCard({
  onPick,
  pickedId,
}: {
  onPick: (s: Scenario) => void;
  pickedId: number | null;
}) {
  const [items, setItems] = useState<Scenario[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ScenariosPayload>(
        "/api/v1/scenarios?include_run_count=true",
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
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.title ?? "").toLowerCase().includes(q),
    );
  }, [items, query]);

  return (
    <Card className="flex flex-col h-full border-border/80 shadow-sm">
      <CardHeader className="space-y-3 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Target className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold leading-none">
                Scenarios
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                {items.length} available · click to select
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={load}
            disabled={loading}
            aria-label="Refresh"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>

        {/* Search filter */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search scenarios..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8 pr-7 h-8 text-xs bg-muted/30 focus-visible:bg-background"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5"
              aria-label="Clear filter"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 px-3 pb-3 pt-0">
        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
            {error}
          </div>
        )}

        {!error && loading && (
          <div className="space-y-2 py-1">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-muted/40"
              />
            ))}
          </div>
        )}

        {!error && !loading && items.length === 0 && (
          <div className="rounded-lg border border-dashed border-border/80 p-6 text-center text-xs text-muted-foreground">
            No scenarios found. Run sync to populate catalog.
          </div>
        )}

        {!error && !loading && items.length > 0 && filtered.length === 0 && (
          <div className="rounded-lg border border-dashed border-border/80 p-6 text-center text-xs text-muted-foreground">
            No scenarios match &quot;{query}&quot;
          </div>
        )}

        <div className="space-y-2 overflow-y-auto max-h-[calc(100vh-280px)] pr-0.5">
          {filtered.map((s) => {
            const isPicked = s.id === pickedId;
            const diffConfig = DIFFICULTY_CONFIG[
              s.difficulty?.toLowerCase() ?? ""
            ] ?? {
              badge: "bg-muted text-muted-foreground border-border",
              icon: <Target className="h-3 w-3" />,
              label: s.difficulty ?? "Standard",
            };

            return (
              <button
                key={s.id}
                onClick={() => onPick(s)}
                className={
                  "group relative w-full rounded-lg border text-left p-3 transition-all " +
                  (isPicked
                    ? "border-primary bg-primary/10 shadow-sm ring-1 ring-primary/30"
                    : "border-border/60 bg-card/60 hover:border-primary/40 hover:bg-accent/40")
                }
              >
                {/* Active Indicator Bar */}
                {isPicked && (
                  <div className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-primary" />
                )}

                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-semibold text-xs leading-tight text-foreground truncate">
                        {s.title || s.name}
                      </span>
                      {s.version !== undefined && s.version > 1 && (
                        <span className="inline-flex items-center rounded bg-primary/15 px-1 py-0.2 text-[9px] font-medium text-primary">
                          v{s.version}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-[11px] text-muted-foreground/80 mt-0.5 truncate">
                      {s.name}
                    </p>
                  </div>

                  <ChevronRight
                    className={
                      "h-4 w-4 shrink-0 transition-transform " +
                      (isPicked
                        ? "text-primary translate-x-0.5"
                        : "text-muted-foreground/40 group-hover:text-muted-foreground group-hover:translate-x-0.5")
                    }
                  />
                </div>

                {/* Badges / Metrics Row */}
                <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                  <span
                    className={
                      "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium " +
                      diffConfig.badge
                    }
                  >
                    {diffConfig.icon}
                    {diffConfig.label}
                  </span>

                  {s.duration_min && (
                    <span className="inline-flex items-center gap-0.5 rounded border border-border/40 bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      <Clock className="h-2.5 w-2.5" />
                      {s.duration_min}m
                    </span>
                  )}

                  {s.run_count !== undefined && s.run_count > 0 && (
                    <span className="inline-flex items-center gap-0.5 rounded border border-border/40 bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      <TrendingUp className="h-2.5 w-2.5" />
                      {s.run_count}
                    </span>
                  )}

                  <span className="ml-auto font-mono text-[10px] text-muted-foreground/60">
                    #{s.id}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
