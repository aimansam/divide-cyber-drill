/**
 * ProfileCard — per-user progress view.
 *
 * The Profile tab on every cyber-range platform shows the user
 * what *they* have done: their runs over time, their success
 * rate, the scenarios they've completed, recent activity.
 *
 * Today this card is just a filtered DashboardCard: the same
 * KPIs, but scoped to the current user. When we add an
 * achievements / skills matrix (L3), this card grows new
 * sections; for now it's a focused "your stats" view that the
 * operator can pin to their browser tab and refer back to.
 *
 * Server-side filtering already gives each user only their own
 * runs (for red/blue) via the role-aware visibility query
 * (see app.services.authorization.visible_runs_query). So the
 * card just renders the existing DashboardCard with no further
 * filtering — the visibility filter IS the profile filter.
 *
 * F-auth-help: also renders RoleCapabilitiesCard so the operator
 * sees what their role is and what they can do, without having
 * to read the source.
 */

import { DashboardCard } from "./dashboard-card";
import { RoleCapabilitiesCard } from "./role-capabilities-card";
import type { Role } from "@/lib/roles";

export function ProfileCard({
  meRole,
  meSub,
}: {
  meRole: Role;
  meSub: string | null;
}) {
  return (
    <div data-testid="profile-card" className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold tracking-tight">
          Your profile
        </h2>
        <p className="text-sm text-muted-foreground">
          Your drills, your success rate, your recent activity.
          {meSub ? (
            <>
              {" "}Showing data scoped to{" "}
              <span className="font-mono">{meSub}</span>.
            </>
          ) : null}
        </p>
      </header>
      <RoleCapabilitiesCard meRole={meRole} meSub={meSub} />
      <DashboardCard
        meRole={meRole}
        meSub={meSub}
        // onPickRun omitted — ProfileCard is a read-only view; the
        // user can click into the Dashboard's recent-runs links
        // and the app navigates to the Observe tab for them.
      />
    </div>
  );
}
