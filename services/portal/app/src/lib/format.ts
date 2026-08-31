/**
 * Shared time/date formatters for the operator UI.
 *
 * Q25: extracted from operator-console-card.tsx (formatRelative) and
 * drill-console.tsx (formatDuration) so all cards render timestamps
 * consistently. Before this refactor, the lifecycle card used raw
 * toLocaleString() while the operator console used relative time,
 * making the same data look like it came from different sources.
 */

/**
 * Relative-time formatter for run rows.
 *
 * Buckets:
 *   * < 60s   -> "Ns ago"
 *   * < 60m   -> "Nm ago"
 *   * < 24h   -> "Nh ago"
 *   * else    -> locale string fallback
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const deltaMs = Date.now() - t;
  const sec = Math.max(0, Math.floor(deltaMs / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return new Date(t).toLocaleString();
}

/**
 * Human-readable duration formatter.
 *
 * Examples:
 *   0     -> "0s"
 *   45    -> "45s"
 *   90    -> "1m 30s"
 *   3661  -> "1h 1m 1s"
 *   -1    -> "—" (invalid)
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}
