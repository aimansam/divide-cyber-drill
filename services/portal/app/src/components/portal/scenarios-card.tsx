import { useEffect, useMemo, useState } from "react";
import {
  Loader2,
  RefreshCw,
  Search,
  X,
  Check,
  Target,
  Clock,
  TrendingUp,
  Shield,
  Zap,
  Skull,
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

// Difficulty configuration with colors and icons
const DIFFICULTY_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  beginner: {
    color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    icon: <Shield className="h-3 w-3" />,
    label: "Beginner",
  },
  intermediate: {
    color: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    icon: <Zap className="h-3 w-3" />,
    label: "Intermediate",
  },
  advanced: {
    color: "bg-red-500/10 text-red-400 border-red-500/20",
    icon: <Skull className="h-3 w-3" />,
    label: "Advanced",
  },
};

/**
 * Scenarios picker card — modern card-based design.
 *
 * Fetches /api/v1/scenarios (public; no token required) on mount and
 * when the user clicks Refresh. Each scenario is rendered as a card
 * with visual difficulty indicators, run metrics, and clear selection state.
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
    <Card className="h-full">
      <CardHeader className="space-y-4 pb-4">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5 text-primary" />
              Scenarios
            </CardTitle>
            <CardDescription className="mt-1">
              {items.length} active scenario{items.length === 1 ? "" : "s"} ·
              Select one to begin
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={load}
            disabled={loading}
            aria-label="Refresh"
            className="h-8 w-8"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
        {/* Search filter */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search scenarios..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9 pr-8 h-9"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Clear filter"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {!error && loading && (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-lg bg-muted/50"
              />
            ))}
          </div>
        )}
        {!error && !loading && items.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-sm text-muted-foreground">
              No scenarios registered.
            </p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Run the scenario sync from the admin endpoints to populate the catalog.
            </p>
          </div>
        )}
        {!error && !loading && items.length > 0 && filtered.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-sm text-muted-foreground">
              No scenarios match &quot;{query}&quot;
            </p>
          </div>
        )}
        <div className="space-y-2">
          {filtered.map((s) => {
            const isPicked = s.id === pickedId;
            const diffConfig = DIFFICULTY_CONFIG[s.difficulty?.toLowerCase() ?? ""] ?? {
              color: "bg-muted text-muted-foreground border-border",
              icon: <Target className="h-3 w-3" />,
              label: s.difficulty ?? "Unknown",
            };

            return (
              <button
                key={s.id}
                onClick={() => onPick(s)}
                className={
                  "group relative w-full rounded-lg border p-4 text-left transition-all duration-200 " +
                  (isPicked
                    ? "border-primary bg-primary/5 shadow-md ring-2 ring-primary/20"
                    : "border-border bg-card hover:border-primary/50 hover:bg-accent/50 hover:shadow-sm")
                }
              >
                {/* Selection indicator */}
                {isPicked && (
                  <div className="absolute top-3 right-3">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary">
                      <Check className="h-3.5 w-3.5 text-primary-foreground" />
                    </div>
                  </div>
                )}

                {/* Header: Name + Difficulty */}
                <div className="flex items-start gap-3 pr-8">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-semibold text-sm text-foreground truncate">
                      {s.title || s.name}
                    </h4>
                    <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                      {s.name}
                    </p>
                  </div>
                </div>

                {/* Meta row: Difficulty + Duration + Runs */}
                <div className="flex items-center gap-2 mt-3 flex-wrap">
                  {/* Difficulty badge */}
                  <span
                    className={
                      "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium " +
                      diffConfig.color
                    }
                  >
                    {diffConfig.icon}
                    {diffConfig.label}
                  </span>

                  {/* Duration */}
                  {s.duration_min && (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      {s.duration_min}m
                    </span>
                  )}

                  {/* Run count */}
                  {s.run_count !== undefined && s.run_count > 0 && (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <TrendingUp className="h-3 w-3" />
                      {s.run_count} run{s.run_count === 1 ? "" : "s"}
                    </span>
                  )}

                  {/* Version */}
                  {s.version !== undefined && s.version > 1 && (
                    <span className="inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      v{s.version}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
