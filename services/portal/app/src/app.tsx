import { useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { TokenBar } from "@/components/portal/token-bar";
import { MyRunsCard, type RunRow } from "@/components/portal/my-runs-card";
import { RunLifecycleCard } from "@/components/portal/run-lifecycle-card";
import { RunInspectorCard } from "@/components/portal/run-inspector-card";
import { AssetsCard } from "@/components/portal/assets-card";
import { AuditExplorerCard } from "@/components/portal/audit-explorer-card";
import { PveOpsCard } from "@/components/portal/pve-ops-card";
import { ScenarioAuthoringCard } from "@/components/portal/scenario-authoring-card";
import { useMe } from "@/lib/auth";
import { ROLE_LABELS, ROLES, type Role } from "@/lib/roles";

/**
 * Top-level portal layout.
 *
 * Role-aware composition (M3.2 Half 2 — complete):
 *
 *   * anonymous  → ScenariosCard + SignInBanner
 *   * admin      → ScenariosCard + PveOpsCard + ScenarioAuthoringCard
 *                  + MyRunsCard + RunLifecycleCard + RunInspectorCard
 *                  + AssetsCard + AuditExplorerCard
 *   * lead       → ScenariosCard + ScenarioAuthoringCard + MyRunsCard
 *                  + RunLifecycleCard + RunInspectorCard + AssetsCard
 *                  + AuditExplorerCard
 *   * red        → ScenariosCard + MyRunsCard + RunLifecycleCard
 *                  + RunInspectorCard + AssetsCard + AuditExplorerCard
 *   * blue       → ScenariosCard + MyRunsCard + RunInspectorCard
 *                  + AssetsCard + AuditExplorerCard (read-only)
 *   * observer   → ScenariosCard + MyRunsCard + RunInspectorCard
 *                  + AuditExplorerCard (read-only)
 *
 * The composition table is the single source of truth.
 *
 *   * Read-only roles (blue, observer) don't get the cards that
 *     have write buttons (RunLifecycleCard with Start + Cancel,
 *     ScenarioAuthoringCard with Import + Archive + Restore).
 *   * Operator roles (admin, lead) get the authoring + PVE-health
 *     surfaces; lead gets authoring but not PVE; admin gets both.
 *   * Red gets the lifecycle (start, refresh, cancel own-only) +
 *     the run-detail + asset + audit reads.
 *   * Observer skips AssetsCard because it's operator-facing detail
 *     (vmids, IPs); RunInspectorCard already surfaces the asset
 *     summary inline.
 *
 * The server-side matrix in `app/routers/drills.py` (commit
 * `4d840f9`) is the second line of defense; if a misbehaving
 * client tried to POST /drills anyway, the role gate would still
 * 403.
 *
 * Identity comes from useMe() which hits GET /api/v1/me. The portal
 * no longer trusts the unverified JWT decode for the identity badge.
 */

/** Card kinds the role router knows about. */
type CardKind =
  | "scenarios"
  | "my-runs"
  | "run-lifecycle"
  | "run-inspector"
  | "assets"
  | "audit-explorer"
  | "pve-ops"
  | "scenario-authoring"
  | "sign-in-banner";

interface CardSpec {
  kind: CardKind;
}

const COMPOSITIONS: Record<"anonymous" | Role, CardSpec[]> = {
  anonymous: [
    { kind: "scenarios" },
    { kind: "sign-in-banner" },
  ],
  admin: [
    { kind: "scenarios" },
    { kind: "pve-ops" }, // admin: read-only PVE health + storage + template
    { kind: "scenario-authoring" }, // admin: import / archive / restore scenarios
    { kind: "my-runs" }, // admin sees "All runs" via ALL_RUNS_ROLES
    { kind: "run-lifecycle" },
    { kind: "run-inspector" },
    { kind: "assets" },
    { kind: "audit-explorer" },
  ],
  lead: [
    { kind: "scenarios" },
    { kind: "scenario-authoring" }, // lead: import / archive / restore scenarios
    { kind: "my-runs" }, // lead sees "All runs" via ALL_RUNS_ROLES
    { kind: "run-lifecycle" },
    { kind: "run-inspector" },
    { kind: "assets" },
    { kind: "audit-explorer" },
  ],
  red: [
    { kind: "scenarios" },
    { kind: "my-runs" },
    { kind: "run-lifecycle" },
    { kind: "run-inspector" },
    { kind: "assets" },
    { kind: "audit-explorer" },
  ],
  blue: [
    { kind: "scenarios" },
    { kind: "my-runs" },
    // blue is read-only — no RunLifecycleCard, no PveOpsCard,
    // no ScenarioAuthoringCard.
    { kind: "run-inspector" },
    { kind: "assets" },
    { kind: "audit-explorer" },
  ],
  observer: [
    { kind: "scenarios" },
    { kind: "my-runs" }, // observer sees "All runs" via ALL_RUNS_ROLES
    // observer cannot start, cannot modify — no RunLifecycleCard,
    // no PveOpsCard, no ScenarioAuthoringCard.
    { kind: "run-inspector" },
    { kind: "audit-explorer" },
    // observer doesn't get AssetsCard either — assets are
    // operator-facing detail. (run-inspector surfaces the
    // asset count and vmid/ip summary inline.)
  ],
};

/** Returns the composition for the verified role, or anonymous. */
function compositionFor(role: Role | null): CardSpec[] {
  if (role === null) return COMPOSITIONS.anonymous;
  return COMPOSITIONS[role];
}

export default function App() {
  const [pickedScenario, setPickedScenario] = useState<Scenario | null>(null);
  const [pickedRun, setPickedRun] = useState<RunRow | null>(null);
  const { me, loading } = useMe();

  // While useMe() is in flight the header says "checking…". We
  // don't render the cards yet either — flashing a composition
  // and then swapping it would be jarring.
  const cards = compositionFor(me?.role ?? null);

  return (
    <div className="min-h-screen bg-background">
      <TokenBar />
      <main className="container mx-auto max-w-3xl space-y-6 py-8">
        <header className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-primary">
            div:ide portal
          </h1>
          <p className="text-sm text-muted-foreground">
            {me ? (
              <>
                Showing the composition for{" "}
                <span className="font-semibold">{ROLE_LABELS[me.role]}</span>.
              </>
            ) : (
              "Run a drill, watch it live, download the debrief. Paste a token above to identify yourself."
            )}
          </p>
        </header>

        {loading && !me && (
          <div className="text-sm italic text-muted-foreground">
            Identifying…
          </div>
        )}

        {cards.map((spec) => {
          switch (spec.kind) {
            case "scenarios":
              return (
                <ScenariosCard
                  key="scenarios"
                  pickedId={pickedScenario?.id ?? null}
                  onPick={setPickedScenario}
                />
              );
            case "my-runs":
              return me ? (
                <MyRunsCard
                  key="my-runs"
                  meRole={me.role}
                  pickedRunId={pickedRun?.id ?? null}
                  onPick={setPickedRun}
                />
              ) : null;
            case "run-lifecycle":
              return me ? (
                <RunLifecycleCard
                  key="run-lifecycle"
                  meSub={me.sub}
                  meRole={me.role}
                  scenario={pickedScenario}
                  pickedRunId={pickedRun?.id ?? null}
                />
              ) : null;
            case "run-inspector":
              return me ? (
                <RunInspectorCard
                  key="run-inspector"
                  pickedRunId={pickedRun?.id ?? null}
                />
              ) : null;
            case "assets":
              return me ? (
                <AssetsCard
                  key="assets"
                  pickedRunId={pickedRun?.id ?? null}
                />
              ) : null;
            case "audit-explorer":
              return me ? (
                <AuditExplorerCard
                  key="audit-explorer"
                  pickedRunId={pickedRun?.id ?? null}
                />
              ) : null;
            case "pve-ops":
              return me ? <PveOpsCard key="pve-ops" /> : null;
            case "scenario-authoring":
              return me ? (
                <ScenarioAuthoringCard key="scenario-authoring" />
              ) : null;
            case "sign-in-banner":
              return (
                <div
                  key="sign-in-banner"
                  className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground"
                >
                  Sign in with a token to run drills. Tokens come from{" "}
                  <code className="font-mono">divide issue-token</code>{" "}
                  (see <a className="underline" href="/portal/">setup</a>
                  {" "}for the wizard). Roles: {ROLES.join(", ")}.
                </div>
              );
            default: {
              const _exhaustive: never = spec.kind;
              void _exhaustive;
              return null;
            }
          }
        })}

        {(pickedScenario || pickedRun) && (
          <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            {pickedScenario ? (
              <>
                Selected scenario:{" "}
                <span className="font-mono">{pickedScenario.name}</span>{" "}
                (id={pickedScenario.id}).
              </>
            ) : null}
            {pickedRun ? (
              <>
                {pickedScenario ? " · " : ""}Selected run:{" "}
                <span className="font-mono">#{pickedRun.id}</span>{" "}
                ({pickedRun.status}
                {pickedRun.started_by ? ` · ${pickedRun.started_by}` : ""}).
                See Run inspector + Assets + Audit log below.
              </>
            ) : null}
          </div>
        )}
      </main>
    </div>
  );
}
