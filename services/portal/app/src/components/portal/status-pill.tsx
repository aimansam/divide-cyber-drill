/**
 * StatusPill — a colored pill that renders a Run / Asset / Scenario
 * status with a tone that matches the F2 audit-explorer color
 * conventions:
 *
 *   * pending  -> slate
 *   * running  -> sky (with pulse dot)
 *   * planned  -> slate
 *   * succeeded / completed -> emerald
 *   * failed   -> red
 *   * timeout  -> amber
 *   * cancelled / stopped -> slate
 *   * orphaned -> orange
 *
 * Unknown statuses get a neutral slate pill with a "?" prefix so
 * a future status addition doesn't silently render blank.
 */

import { cn } from "@/lib/utils";

export type StatusTone =
  | "pending"
  | "running"
  | "planned"
  | "succeeded"
  | "completed"
  | "failed"
  | "timeout"
  | "cancelled"
  | "stopped"
  | "orphaned"
  | "unknown";

const TONE_CLASS: Record<StatusTone, string> = {
  pending: "bg-slate-800/60 text-slate-300 ring-slate-700",
  running: "bg-sky-900/50 text-sky-200 ring-sky-700",
  planned: "bg-slate-800/40 text-slate-400 ring-slate-700",
  succeeded: "bg-emerald-900/50 text-emerald-200 ring-emerald-700",
  completed: "bg-emerald-900/50 text-emerald-200 ring-emerald-700",
  failed: "bg-red-900/60 text-red-200 ring-red-700",
  timeout: "bg-amber-900/60 text-amber-200 ring-amber-700",
  cancelled: "bg-slate-800/40 text-slate-400 ring-slate-700",
  stopped: "bg-slate-800/40 text-slate-400 ring-slate-700",
  orphaned: "bg-orange-900/60 text-orange-200 ring-orange-700",
  unknown: "bg-slate-800/40 text-slate-500 ring-slate-700",
};

export function statusTone(s: string | null | undefined): StatusTone {
  if (!s) return "unknown";
  const v = s.toLowerCase();
  if (v === "running" || v === "cloning" || v === "booting") return "running";
  if (v === "pending") return "pending";
  if (v === "planned") return "planned";
  if (v === "succeeded" || v === "completed") return "succeeded";
  if (v === "failed") return "failed";
  if (v === "timeout") return "timeout";
  if (v === "cancelled" || v === "canceled") return "cancelled";
  if (v === "stopped") return "stopped";
  if (v === "orphaned") return "orphaned";
  return "unknown";
}

export function StatusPill({
  status,
  className,
}: {
  status: string | null | undefined;
  className?: string;
}) {
  const tone = statusTone(status);
  const label = status ?? "unknown";
  return (
    <span
      data-testid="status-pill"
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium uppercase tracking-wide ring-1 ring-inset",
        TONE_CLASS[tone],
        className,
      )}
    >
      {tone === "running" && (
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300"
        />
      )}
      {label}
    </span>
  );
}
