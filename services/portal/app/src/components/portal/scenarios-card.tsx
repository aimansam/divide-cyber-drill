import { useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, Search, X } from "lucide-react";
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

/**
 * Scenarios picker card.
 *
 * Fetches /api/v1/scenarios (public; no token required) on mount and
 * when the user clicks Refresh. Each row is a button that calls
 * `onPick` with the full scenario row, which the parent App hands to
 * the run-lifecycle card via shared state.
 *
 * Features:
 *   - Text search filter (name + title)
 *   - Version badge
 *   - Run count (times executed)
 *   - Loading skeleton
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
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Scenarios</CardTitle>
            <CardDescription>
              {items.length} active scenario{items.length === 1 ? "" : "s"} ·
              click one to load it for the run panel
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
        </div>
        {/* Search filter */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter scenarios…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8 pr-8 h-8 text-sm"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="Clear filter"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {error && <div className="text-sm text-destructive">{error}</div>}
        {!error && loading && (
          <ul className="space-y-1">
            {[0, 1, 2].map((i) => (
              <li key={i} className="h-14 animate-pulse rounded bg-muted/50" />
            ))}
          </ul>
        )}
        {!error && !loading && items.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            No scenarios registered. Run the scenario sync from the admin
            endpoints to populate the catalog.
          </div>
        )}
        {!error && !loading && items.length > 0 && filtered.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            No scenarios match &quot;{query}&quot;.
          </div>
        )}
        <ul className="divide-y divide-border">
          {filtered.map((s) => {
            const isPicked = s.id === pickedId;
            return (
              <li key={s.id}>
                <button
                  onClick={() => onPick(s)}
                  className={
                    "flex w-full items-center justify-between gap-3 px-2 py-3 text-left transition-colors hover:bg-accent " +
                    (isPicked ? "bg-accent" : "")
                  }
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm truncate">
                        {s.name}
                      </span>
                      {s.version !== undefined && s.version > 1 && (
                        <span className="inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          v{s.version}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {s.title || s.name}
                      {s.difficulty ? ` · ${s.difficulty}` : ""}
                      {s.duration_min ? ` · ${s.duration_min}m` : ""}
                      {s.run_count !== undefined && (
                        <span className="ml-1 text-muted-foreground/70">
                          · {s.run_count} run{s.run_count === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground shrink-0">
                    id={s.id}
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
