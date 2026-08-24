/**
 * TopologyGraph — SVG visual of a scenario's asset layout.
 *
 * Real cyber ranges always show a network map. RangeForce calls it
 * "Battle Range", HackTheBox has "Network Map" inside Pro Labs,
 * Immersive Labs shows it on the live exercise screen, CyLab
 * shows it on the dashboard. The visual identity of the platform
 * hinges on this one widget.
 *
 * Today we have only the legacy single-asset scenario; the graph
 * renders whatever assets the scenario defines, laid out as a
 * left-to-right red<->blue topology with a router in the middle.
 * When F3 ships (multi-VM scenarios with networks[]), this graph
 * gains real segments and bridges; the layout code stays the same.
 *
 * No external dep: pure SVG + Tailwind. Works in any browser,
 * scales to any size, accessible via title + aria-label.
 *
 * Asset role zones (left to right):
 *   red zone  ── router / firewall ──  blue zone
 *
 * Roles we know how to lay out:
 *   * attacker / red          → red zone
 *   * victim / target          → blue zone
 *   * defender                 → blue zone
 *   * router / firewall        → middle (router)
 *   * log-aggregator / syslog  → blue zone (collector)
 *   * drill_vm                 → blue zone (generic drill VM)
 *
 * Roles we don't recognise land in the middle as "unassigned".
 */

import { useMemo } from "react";
import { Network } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TopologyAsset {
  /** A stable id for React key. */
  id: string;
  /** Free-form role string from the scenario YAML. */
  role: string;
  /** Optional display name; defaults to role. */
  label?: string;
}

type Zone = "red" | "router" | "blue" | "unassigned";

function classifyRole(role: string): Zone {
  const v = role.toLowerCase();
  if (
    v.includes("attacker") ||
    v.includes("red") ||
    v.includes("offensive") ||
    v.includes("pentester")
  ) {
    return "red";
  }
  if (v.includes("router") || v.includes("firewall") || v.includes("gw")) {
    return "router";
  }
  if (
    v.includes("victim") ||
    v.includes("defender") ||
    v.includes("blue") ||
    v.includes("target") ||
    v.includes("log-aggregator") ||
    v.includes("syslog") ||
    v.includes("drill_vm") ||
    v.includes("server") ||
    v.includes("workstation") ||
    v.includes("client")
  ) {
    return "blue";
  }
  return "unassigned";
}

const ZONE_FILL: Record<Zone, string> = {
  red: "hsl(0 65% 22%)",
  router: "hsl(40 60% 22%)",
  blue: "hsl(210 70% 22%)",
  unassigned: "hsl(220 15% 25%)",
};

const ZONE_STROKE: Record<Zone, string> = {
  red: "hsl(0 65% 50%)",
  router: "hsl(40 60% 55%)",
  blue: "hsl(210 70% 55%)",
  unassigned: "hsl(220 15% 50%)",
};

const ZONE_LABEL: Record<Zone, string> = {
  red: "Red team",
  router: "Router / firewall",
  blue: "Blue team / victims",
  unassigned: "Other",
};

const NODE_W = 140;
const NODE_H = 56;
const NODE_GAP_Y = 18;
const PADDING = 16;
const ZONE_GAP = 80;

export function TopologyGraph({
  assets,
  className,
}: {
  assets: TopologyAsset[];
  className?: string;
}) {
  const layout = useMemo(() => {
    // Bucket assets by zone.
    const buckets: Record<Zone, TopologyAsset[]> = {
      red: [],
      router: [],
      blue: [],
      unassigned: [],
    };
    for (const a of assets) buckets[classifyRole(a.role)].push(a);

    const order: Zone[] = ["red", "router", "blue", "unassigned"];
    // Hide empty zones so the diagram shrinks to fit.
    const zones = order.filter((z) => buckets[z].length > 0);

    // Per-zone vertical stacks; max column height drives the height.
    let maxStackHeight = 0;
    const positions: Array<{
      asset: TopologyAsset;
      zone: Zone;
      x: number;
      y: number;
    }> = [];
    let cursorX = PADDING;
    zones.forEach((zone, zi) => {
      const stack = buckets[zone];
      const stackHeight = stack.length * NODE_H + (stack.length - 1) * NODE_GAP_Y;
      maxStackHeight = Math.max(maxStackHeight, stackHeight);
      const startY = PADDING + (maxStackHeight - stackHeight) / 2;
      stack.forEach((asset, i) => {
        positions.push({
          asset,
          zone,
          x: cursorX,
          y: startY + i * (NODE_H + NODE_GAP_Y),
        });
      });
      cursorX += NODE_W + (zi < zones.length - 1 ? ZONE_GAP : PADDING);
    });

    const width = cursorX + (zones.length === 0 ? PADDING * 2 : 0);
    const height = maxStackHeight + PADDING * 2;
    return { positions, width, height, zones };
  }, [assets]);

  if (assets.length === 0) {
    return (
      <div
        data-testid="topology-graph"
        className={cn(
          "flex items-center justify-center rounded-md border border-dashed border-border bg-card/40 p-6 text-sm text-muted-foreground",
          className,
        )}
      >
        <Network className="mr-2 h-4 w-4" aria-hidden="true" />
        Pick a scenario to see its network topology.
      </div>
    );
  }

  return (
    <div
      data-testid="topology-graph"
      role="img"
      aria-label={`Network topology: ${assets.length} asset${assets.length === 1 ? "" : "s"}`}
      className={cn(
        "rounded-md border border-border bg-card p-2 shadow-sm",
        className,
      )}
    >
      <svg
        viewBox={`0 0 ${Math.max(layout.width, 200)} ${Math.max(layout.height, 100)}`}
        width="100%"
        height={Math.max(layout.height, 100)}
        preserveAspectRatio="xMidYMid meet"
      >
        {layout.zones.map((zone) => {
          // Compute zone background rect by finding min/max x of its nodes.
          const inZone = layout.positions.filter((p) => p.zone === zone);
          if (inZone.length === 0) return null;
          const minX = Math.min(...inZone.map((p) => p.x)) - 8;
          const maxX = Math.max(...inZone.map((p) => p.x)) + NODE_W + 8;
          const minY = Math.min(...inZone.map((p) => p.y)) - 8;
          const maxY = Math.max(...inZone.map((p) => p.y)) + NODE_H + 8;
          const x = layout.zones.indexOf(zone);
          const labelX = minX + 8;
          const labelY = minY - 4 < 14 ? maxY + 14 : minY - 4;
          return (
            <g key={zone}>
              <rect
                x={minX}
                y={minY}
                width={maxX - minX}
                height={maxY - minY}
                fill={ZONE_FILL[zone]}
                stroke={ZONE_STROKE[zone]}
                strokeWidth={1}
                strokeDasharray="4 4"
                rx={6}
              />
              <text
                x={labelX}
                y={labelY}
                fill={ZONE_STROKE[zone]}
                fontSize={11}
                fontFamily="monospace"
                fontWeight={600}
                textAnchor="start"
              >
                {ZONE_LABEL[zone]} ({inZone.length})
              </text>
              {/* Suppress unused var lint */}
              {void x}
            </g>
          );
        })}
        {/* Connection lines red↔router↔blue */}
        {layout.zones.includes("red") &&
          layout.zones.includes("router") && (
            <line
              x1={
                Math.max(
                  ...layout.positions
                    .filter((p) => p.zone === "red")
                    .map((p) => p.x + NODE_W),
                ) + 4
              }
              y1={
                layout.positions.find((p) => p.zone === "router")!.y + NODE_H / 2
              }
              x2={
                layout.positions.find((p) => p.zone === "router")!.x - 4
              }
              y2={
                layout.positions.find((p) => p.zone === "router")!.y + NODE_H / 2
              }
              stroke="hsl(0 0% 60%)"
              strokeWidth={2}
              strokeDasharray="3 3"
            />
          )}
        {layout.zones.includes("router") &&
          layout.zones.includes("blue") && (
            <line
              x1={
                layout.positions.find((p) => p.zone === "router")!.x + NODE_W + 4
              }
              y1={
                layout.positions.find((p) => p.zone === "router")!.y + NODE_H / 2
              }
              x2={
                Math.min(
                  ...layout.positions
                    .filter((p) => p.zone === "blue")
                    .map((p) => p.x),
                ) - 4
              }
              y2={
                layout.positions.find((p) => p.zone === "blue")!.y + NODE_H / 2
              }
              stroke="hsl(0 0% 60%)"
              strokeWidth={2}
              strokeDasharray="3 3"
            />
          )}
        {layout.positions.map((pos) => (
          <g key={pos.asset.id}>
            <rect
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
              rx={4}
              fill="hsl(220 15% 18%)"
              stroke={ZONE_STROKE[pos.zone]}
              strokeWidth={1.5}
            />
            <text
              x={pos.x + NODE_W / 2}
              y={pos.y + 22}
              fill="hsl(0 0% 95%)"
              fontSize={12}
              fontFamily="monospace"
              fontWeight={600}
              textAnchor="middle"
            >
              {pos.asset.label ?? pos.asset.role}
            </text>
            <text
              x={pos.x + NODE_W / 2}
              y={pos.y + 40}
              fill="hsl(0 0% 70%)"
              fontSize={10}
              fontFamily="monospace"
              textAnchor="middle"
            >
              {pos.asset.role}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
