/**
 * KpiTile — one metric, one big number, optional sublabel.
 *
 * Used by DashboardCard. Designed to be readable at a glance on
 * any screen size (text-3xl number, text-xs label). The optional
 * ``tone`` adjusts the number color (red for failures, emerald
 for
 * successes) so the operator can scan a row of tiles and see
 * "3 red, 7 green" without reading.
 */

import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "default" | "success" | "danger" | "warning" | "info";

const TONE_CLASS: Record<Tone, string> = {
  default: "text-foreground",
  success: "text-emerald-300",
  danger: "text-red-300",
  warning: "text-amber-300",
  info: "text-sky-300",
};

export function KpiTile({
  label,
  value,
  sublabel,
  icon,
  tone = "default",
  loading,
}: {
  label: string;
  value: number | string;
  sublabel?: string;
  icon?: LucideIcon;
  tone?: Tone;
  loading?: boolean;
}) {
  const Icon = icon;
  return (
    <div
      data-testid="kpi-tile"
      data-tone={tone}
      className="flex flex-col gap-1 rounded-md border border-border bg-card p-4 shadow-sm"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
      </div>
      <div
        className={cn(
          "font-mono text-3xl font-semibold tabular-nums",
          TONE_CLASS[tone],
        )}
      >
        {loading ? "…" : value}
      </div>
      {sublabel ? (
        <div className="text-xs text-muted-foreground">{sublabel}</div>
      ) : null}
    </div>
  );
}
