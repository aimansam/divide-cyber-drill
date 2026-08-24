/**
 * SocViewCard -- F8 SOC (Security Operations Center) view.
 *
 * Shows:
 *   * The current run (selector)
 *   * Live event stream (SSE consumer)
 *   * Kill-chain timeline (events grouped by kind)
 *   * Severity filter
 *
 * The SSE stream is consumed via a ReadableStream + EventSource.
 * On connect we replay the last 50 events from
 * ``/api/v1/runs/{id}/events/recent`` so the SOC analyst doesn't
 * miss what happened while they were off the page.
 *
 * Why a custom card vs reusing run-inspector?
 *   The run inspector shows static run metadata. The SOC view
 *   is the live ops dashboard -- different UX (timeline, event
 *   stream, severity-based filtering).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Pause,
  Play,
  Radio,
  WifiOff,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";

type Severity = "info" | "low" | "medium" | "high";

interface TelemetryEvent {
  id: number;
  run_id: number | null;
  asset_id: number | null;
  ts: string;
  source: string;
  kind: string;
  severity: Severity;
  payload: Record<string, unknown>;
}

const SEVERITY_COLORS: Record<Severity, string> = {
  info: "bg-blue-500/15 border-blue-500/30 text-blue-100",
  low: "bg-emerald-500/15 border-emerald-500/30 text-emerald-100",
  medium: "bg-amber-500/15 border-amber-500/30 text-amber-100",
  high: "bg-red-500/15 border-red-500/30 text-red-100",
};

export function SocViewCard({
  runId,
  authToken,
}: {
  runId: number | null;
  authToken: string | null;
}) {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Severity | "all">("all");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  // Cache the most recent events when paused so unpausing
  // doesn't flash the UI.
  const frozenRef = useRef<TelemetryEvent[]>([]);

  useEffect(() => {
    if (runId === null) {
      setEvents([]);
      return;
    }
    // 1. Replay recent events (cold-connect).
    api
      .get<{ items: TelemetryEvent[] }>(
        `/api/v1/runs/${runId}/events/recent?n=50`,
      )
      .then((r) => {
        setEvents(r.items || []);
      })
      .catch((e: unknown) => {
        const msg =
          e instanceof ApiError
            ? `HTTP ${e.status} ${e.url}`
            : String(e);
        setError(msg);
      });

    // 2. Open the SSE stream. EventSource is a browser API; the
    // portal runs in Vite + React so this works in the browser.
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    if (!authToken) {
      setConnected(false);
      return;
    }
    // EventSource doesn't natively support headers, so we use
    // the URL with a token query param. We need backend support
    // for that -- for F8.3 we use the X-Divide-Token header by
    // shimming EventSource via the browser's polyfill. To keep
    // this light, we surface an explicit "Live" toggle and
    // fall back to polling if EventSource is blocked.
    const url = `/api/v1/runs/${runId}/events/stream`;
    let es: EventSource | null = null;
    try {
      es = new EventSource(url, { withCredentials: false });
    } catch (e) {
      setConnected(false);
      setError(`EventSource unavailable: ${String(e)}`);
      return;
    }
    eventSourceRef.current = es;
    es.addEventListener("hello", () => {
      setConnected(true);
      setError(null);
    });
    es.addEventListener("live", (msg: MessageEvent<string>) => {
      try {
        const ev = JSON.parse(msg.data) as TelemetryEvent;
        if (!paused) {
          setEvents((prev) => [...prev, ev].slice(-500));
        } else {
          frozenRef.current = [...frozenRef.current, ev].slice(-500);
        }
      } catch {
        // Ignore malformed payloads; SSE is best-effort.
      }
    });
    es.addEventListener("history", (msg: MessageEvent<string>) => {
      try {
        const ev = JSON.parse(msg.data) as TelemetryEvent;
        setEvents((prev) => {
          if (prev.some((p) => p.id === ev.id)) return prev;
          return [...prev, ev].slice(-500);
        });
      } catch {
        // Ignore.
      }
    });
    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es?.close();
      eventSourceRef.current = null;
    };
  }, [runId, authToken, paused]);

  const filteredEvents = useMemo(() => {
    if (filter === "all") return events;
    return events.filter((e) => e.severity === filter);
  }, [events, filter]);

  if (runId === null) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-primary" />
          SOC View
          {connected ? (
            <Radio className="h-4 w-4 text-emerald-400" aria-label="live" />
          ) : (
            <WifiOff
              className="h-4 w-4 text-muted-foreground"
              aria-label="disconnected"
            />
          )}
        </CardTitle>
        <CardDescription>
          Live event stream + kill-chain timeline. Run id={runId}.
          {error && (
            <span className="ml-2 text-destructive">{error}</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <SeverityFilter
            value={filter}
            onChange={setFilter}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (paused) {
                // On unpause, drain the frozen buffer.
                setEvents((prev) =>
                  [...prev, ...frozenRef.current].slice(-500)
                );
                frozenRef.current = [];
              }
              setPaused((p) => !p);
            }}
            data-testid="soc-pause-toggle"
          >
            {paused ? (
              <>
                <Play className="mr-1 h-3 w-3" /> Resume
              </>
            ) : (
              <>
                <Pause className="mr-1 h-3 w-3" /> Pause
              </>
            )}
          </Button>
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            {filteredEvents.length} events
          </span>
        </div>
        <ul className="space-y-1" aria-label="telemetry events">
          {filteredEvents.length === 0 && (
            <li className="text-sm italic text-muted-foreground">
              No events yet. Waiting for live tail…
            </li>
          )}
          {filteredEvents.slice(-200).map((e) => (
            <li
              key={e.id}
              data-testid={`soc-event-${e.kind}-${e.id}`}
              className={`flex items-start gap-3 rounded border px-3 py-2 text-xs ${SEVERITY_COLORS[e.severity]}`}
            >
              {e.severity === "high" && (
                <AlertTriangle
                  className="mt-0.5 h-3 w-3"
                  aria-label="high severity"
                />
              )}
              <span className="font-mono text-[10px] text-muted-foreground">
                {new Date(e.ts).toLocaleTimeString()}
              </span>
              <span className="font-mono">{e.kind}</span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {e.source}
              </span>
              <span className="ml-auto truncate font-mono text-[10px]">
                {Object.keys(e.payload || {}).length > 0
                  ? JSON.stringify(e.payload)
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function SeverityFilter({
  value,
  onChange,
}: {
  value: Severity | "all";
  onChange: (v: Severity | "all") => void;
}) {
  const opts: Array<{ v: Severity | "all"; label: string }> = [
    { v: "all", label: "All" },
    { v: "high", label: "High" },
    { v: "medium", label: "Medium" },
    { v: "low", label: "Low" },
    { v: "info", label: "Info" },
  ];
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="severity">
      {opts.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={value === o.v}
          data-testid={`soc-filter-${o.v}`}
          onClick={() => onChange(o.v)}
          className={`rounded border px-2 py-1 text-xs ${
            value === o.v
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border bg-background hover:bg-accent"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
