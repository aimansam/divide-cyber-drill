/**
 * LeaderboardCard -- F6 multi-team score view.
 *
 * Fetches ``GET /api/v1/exercises/{id}/leaderboard`` and renders a
 * ranked bar chart. Currently triggered from the Admin tab; we
 * also surface it on the Operator console view when a live
 * exercise is selected.
 *
 * Visual: horizontal bars per team, color matches Team.color from
 * the API. Highest-score team gets a small crown emoji.
 *
 * Why a custom canvas-free chart instead of recharts / chart.js?
 * The portal bundle has a 280 KB budget; both libs add ~80 KB. A
 * CSS-based bar is < 1 KB and reads better in the F4-UI dark
 * theme anyway.
 */

import { useEffect, useState } from "react";
import { Crown, Trophy } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { api, detailFromError } from "@/lib/api";

interface LeaderboardTeam {
  rank: number;
  team_id: number;
  name: string;
  color: string;
  score: number;
}

interface LeaderboardPayload {
  exercise_id: number;
  exercise_name: string;
  exercise_title: string;
  exercise_status: string;
  teams: LeaderboardTeam[];
}

export function LeaderboardCard({
  exerciseId,
  pollIntervalMs = 0,
}: {
  exerciseId: number | null;
  /**
   * Polling interval in milliseconds. ``0`` (the default) means
   * fetch-once-on-mount, which is the right behavior for the
   * Admin tab (the operator manually refreshes when they care).
   *
   * F9.2: the DrillConsole embed mode passes ``5000`` so the
   * leaderboard ticks live alongside the SOC stream. The
   * existing single-fetch path stays untouched; F9.2 only adds
   * the optional interval.
   */
  pollIntervalMs?: number;
}) {
  const [data, setData] = useState<LeaderboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (exerciseId === null) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    async function fetchOnce() {
      setLoading(true);
      try {
        const r = await api.get<LeaderboardPayload>(
          `/api/v1/exercises/${exerciseId}/leaderboard`,
        );
        if (cancelled) return;
        setData(r);
        setError(null);
      } catch (e: unknown) {
        if (cancelled) return;
        setError(detailFromError(e));
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void fetchOnce();

    // F9.2: poll-mode. Off (pollIntervalMs <= 0) preserves the
    // pre-F9.2 fetch-once-on-mount behavior for callers that
    // don't pass a positive interval (i.e., the Admin tab).
    if (pollIntervalMs > 0) {
      timer = setInterval(() => {
        void fetchOnce();
      }, pollIntervalMs);
    }

    return () => {
      cancelled = true;
      if (timer !== null) clearInterval(timer);
    };
  }, [exerciseId, pollIntervalMs]);

  if (exerciseId === null) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Trophy className="h-5 w-5 text-primary" />
          Leaderboard
        </CardTitle>
        <CardDescription>
          {loading && "Loading…"}
          {!loading && data && (
            <span>
              <span className="font-mono">{data.exercise_name}</span> ·{" "}
              <span className="text-xs uppercase tracking-wide">
                {data.exercise_status}
              </span>
            </span>
          )}
          {!loading && error && (
            <span className="text-destructive">{error}</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data && data.teams.length === 0 && (
          <div className="text-sm italic text-muted-foreground">
            No teams yet.
          </div>
        )}
        {data && data.teams.length > 0 && (
          <LeaderboardBar teams={data.teams} />
        )}
      </CardContent>
    </Card>
  );
}

/**
 * LeaderboardBar -- CSS-based horizontal bars.
 *
 * Each row is a team. Bar width = (score / max_score) * 100%.
 * First-place team shows a small Crown icon.
 */
function LeaderboardBar({ teams }: { teams: LeaderboardTeam[] }) {
  const max = Math.max(1, ...teams.map((t) => t.score));
  return (
    <ul className="space-y-2" aria-label="team scores">
      {teams.map((t) => {
        const pct = max === 0 ? 0 : Math.round((t.score / max) * 100);
        const isFirst = t.rank === 1;
        return (
          <li
            key={t.team_id}
            data-testid={`leaderboard-team-${t.name}`}
            className="flex items-center gap-3 rounded border border-border bg-card/40 px-3 py-2 text-sm"
          >
            <span className="w-6 text-right font-mono text-muted-foreground">
              #{t.rank}
            </span>
            {isFirst ? (
              <Crown
                className="h-4 w-4 text-amber-400"
                aria-label="first place"
              />
            ) : (
              <span className="h-4 w-4" aria-hidden="true" />
            )}
            <span className="min-w-[6rem] font-mono">{t.name}</span>
            <div
              className="relative h-4 flex-1 overflow-hidden rounded bg-secondary"
              role="progressbar"
              aria-valuenow={t.score}
              aria-valuemin={0}
              aria-valuemax={max}
            >
              <div
                className="absolute inset-y-0 left-0"
                style={{
                  width: `${pct}%`,
                  backgroundColor: t.color,
                  transition: "width 240ms ease-out",
                }}
              />
            </div>
            <span className="w-12 text-right font-mono tabular-nums">
              {t.score}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
