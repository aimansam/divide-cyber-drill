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
import { api, detailFromError } from "@/lib/api";

export interface Scenario {
  id: number;
  name: string;
  title?: string;
  difficulty?: string;
  duration_min?: number;
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

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ScenariosPayload>("/api/v1/scenarios");
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

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Scenarios</CardTitle>
          <CardDescription>
            {items.length} active scenario{items.length === 1 ? "" : "s"} ·
            click one to load it for the run panel
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
            No scenarios registered. Run the scenario sync from the admin
            endpoints to populate the catalog.
          </div>
        )}
        <ul className="divide-y divide-border">
          {items.map((s) => {
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
                  <div>
                    <div className="font-mono text-sm">{s.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.title || s.name}
                      {s.difficulty ? ` · ${s.difficulty}` : ""}
                      {s.duration_min ? ` · ${s.duration_min}m` : ""}
                    </div>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">
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
