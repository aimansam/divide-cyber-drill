/**
 * RoleCapabilitiesCard — "What you can do" reference for the current role.
 *
 * Goal: a new operator lands on the portal, signs in, and immediately
 * knows which role they have and what that role is allowed to do.
 *
 * Layout (top → bottom):
 *   1. "You are signed in as {sub} · {role}" header (data from /me).
 *   2. Your persona — one paragraph explaining the role.
 *   3. "What you can do" — a check-list of permissions for YOUR role.
 *   4. "Compare roles" — a compact matrix with all five roles as
 *      rows and capabilities as columns. Your row is highlighted.
 *
 * The capability list is derived from the server's `require_role()`
 * gates in services/api/app/routers/*.py. If you add or change a
 * role gate, update ROLE_PERMISSIONS / CAPABILITY_GROUPS below to
 * keep the matrix in sync. There is no auto-discovery from the API
 * surface (the routers don't expose their allow-list) — this card
 * is the canonical reference for operators.
 *
 * The data is intentionally a const literal rather than fetched
 * from the API: it changes only when the codebase changes, and
 * keeping it client-side avoids a network round-trip on every
 * Profile tab render.
 */
import { ROLES, ROLE_LABELS, type Role } from "@/lib/roles";

interface Capability {
  id: string;
  label: string;
  description: string;
}

interface RolePermissions {
  title: string;
  permissionIds: readonly string[];
}

/**
 * Capability catalogue. New capabilities go here; the matrix auto-renders.
 * Keep labels short (≤24 chars) so the table fits on one screen.
 */
const CAPABILITY_GROUPS: readonly Capability[] = [
  { id: "start_drill", label: "Start a drill", description: "Launch a new drill from a scenario" },
  { id: "cancel_own_drill", label: "Cancel own drill", description: "Cancel a drill you started" },
  { id: "cancel_any_drill", label: "Cancel any drill", description: "Cancel a drill started by anyone" },
  { id: "stop_drill", label: "Force-stop", description: "Force a running drill to stop immediately" },
  { id: "reset_drill", label: "Reset drill", description: "Restore a drill to its template snapshot" },
  { id: "view_all_runs", label: "View runs", description: "See runs started by anyone (red/blue see only their own)" },
  { id: "submit_flag", label: "Submit flags", description: "Capture a flag from a drill VM for scoring" },
  { id: "download_vpn", label: "VPN config", description: "Get a per-user WireGuard config to reach drill VMs" },
  { id: "view_audit", label: "Audit log", description: "See the per-run audit trail (asset spawned, flag planted, etc.)" },
  { id: "view_leaderboard", label: "Leaderboard", description: "See team scores in multi-team exercises" },
  { id: "author_scenarios", label: "Author scenarios", description: "Import / edit scenario YAML" },
  { id: "manage_users", label: "Manage users", description: "Create accounts, toggle disabled, assign roles" },
  { id: "manage_pve", label: "Manage Proxmox", description: "Upload qcow2 templates, set canonical drill template" },
];

/**
 * Per-role permission set. The matrix is built from this + CAPABILITY_GROUPS.
 * Keep in sync with the server's `require_role()` gates (see
 * services/api/app/routers/*.py) and docs/USER-REQUIREMENTS.md §2.
 */
const ROLE_PERMISSIONS: Record<Role, RolePermissions> = {
  admin: {
    title: "Platform admin",
    permissionIds: [
      "start_drill", "cancel_own_drill", "cancel_any_drill",
      "stop_drill", "reset_drill", "view_all_runs",
      "submit_flag", "download_vpn", "view_audit", "view_leaderboard",
      "author_scenarios", "manage_users", "manage_pve",
    ],
  },
  lead: {
    title: "Drill lead / instructor",
    permissionIds: [
      "start_drill", "cancel_own_drill", "cancel_any_drill",
      "stop_drill", "reset_drill", "view_all_runs",
      "submit_flag", "download_vpn", "view_audit", "view_leaderboard",
      "author_scenarios",
    ],
  },
  red: {
    title: "Red team (offensive)",
    permissionIds: [
      "start_drill", "cancel_own_drill",
      "view_all_runs", "submit_flag", "download_vpn", "view_audit", "view_leaderboard",
    ],
  },
  blue: {
    title: "Blue team (defensive)",
    permissionIds: [
      "view_all_runs", "submit_flag", "download_vpn", "view_audit", "view_leaderboard",
    ],
  },
  observer: {
    title: "Observer (read-only)",
    permissionIds: [
      "view_all_runs", "view_audit", "view_leaderboard",
    ],
  },
};

interface RoleCapabilitiesCardProps {
  meRole: Role;
  meSub: string | null;
}

export function RoleCapabilitiesCard({ meRole, meSub }: RoleCapabilitiesCardProps) {
  const mine = ROLE_PERMISSIONS[meRole];

  return (
    <div
      data-testid="role-capabilities-card"
      className="space-y-4 rounded-md border border-border bg-card p-5"
    >
      <header className="space-y-1">
        <h3 className="text-base font-semibold tracking-tight">What you can do</h3>
        <p className="text-sm text-muted-foreground">
          You are signed in as{" "}
          <span className="font-mono text-foreground">{meSub ?? "?"}</span> ·{" "}
          <span className="rounded bg-secondary/40 px-1.5 py-0.5 text-xs font-semibold text-secondary-foreground">
            {ROLE_LABELS[meRole]}
          </span>
        </p>
      </header>

      <section className="rounded-md bg-muted/30 p-3">
        <p className="text-sm font-medium">{mine.title}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          The matrix below compares you against every role.
        </p>
      </section>

      <section>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Compare all roles
        </h4>
        <div
          role="table"
          aria-label="Permissions matrix"
          className="rounded-md border border-border text-xs overflow-hidden"
          style={{ display: "grid", gridTemplateColumns: `1.4fr repeat(${ROLES.length}, 1fr)` }}
        >
          {/* Header row */}
          <div role="row" className="bg-muted/40 font-medium">
            <div role="columnheader" className="px-3 py-2">Capability</div>
            {ROLES.map((r) => (
              <div
                key={r}
                role="columnheader"
                className={`px-2 py-2 text-center ${r === meRole ? "bg-primary/10 text-primary" : "text-muted-foreground"}`}
              >
                {ROLE_LABELS[r]}
              </div>
            ))}
          </div>
          {/* Data rows */}
          {CAPABILITY_GROUPS.map((c) => (
            <div role="row" key={c.id} className="border-t border-border">
              <div role="cell" className="px-3 py-1.5" title={c.description}>{c.label}</div>
              {ROLES.map((r) => {
                const ok = ROLE_PERMISSIONS[r].permissionIds.includes(c.id);
                return (
                  <div
                    key={r}
                    role="cell"
                    className={`px-2 py-1.5 text-center ${r === meRole ? "bg-primary/5" : ""}`}
                  >
                    {ok ? <span className="text-emerald-500">✓</span> : <span className="text-muted-foreground/30">—</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Your role is highlighted. Hover a row for the full description.
        </p>
      </section>
    </div>
  );
}
