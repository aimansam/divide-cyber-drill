import { useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { TokenBar } from "@/components/portal/token-bar";
import { MyRunsCard, type RunRow } from "@/components/portal/my-runs-card";
import { RunLifecycleCard } from "@/components/portal/run-lifecycle-card";
import { useMe } from "@/lib/auth";
import { ROLE_LABELS, ROLES, type Role } from "@/lib/roles";

/**
 * Top-level portal layout.
 *
 * Role-aware composition (M3.2, Half 1):
 *
 *   * anonymous  → ScenariosCard + SignInBanner
 *   * admin      → ScenariosCard + MyRunsCard (as "All runs") + RunLifecycleCard
 *   * lead       → ScenariosCard + MyRunsCard (as "All runs") + RunLifecycleCard
 *   * red        → ScenariosCard + MyRunsCard (as "My runs")    + RunLifecycleCard
 *   * blue       → ScenariosCard + MyRunsCard (as "My runs")    (read-only)
 *   * observer   → ScenariosCard + MyRunsCard (as "All runs")   (read-only)
 *
 * The composition table is the single source of truth: blue and
 * observer don't get RunLifecycleCard at all, so they can't click
 * "Start drill" and get 403. The server-side matrix in
 * `app/routers/drills.py` (commit 4d840f9) is the second line of
 * defense; if a misbehaving client tried to POST /drills anyway,
 * the role gate would still 403.
 *
 * Identity comes from useMe() which hits GET /api/v1/me. The portal
 * no longer trusts the unverified JWT decode for the identity badge.
 *
 * Half 2 will add: RunInspectorCard, AssetsCard, AuditExplorerCard,
 * PveOpsCard (admin), ScenarioAuthoringCard (admin + lead).
 */

/** Card kinds the role router knows about. Half 2 will extend. */
type CardKind =
  | "scenarios"
  | "my-runs"
  | "run-lifecycle"
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
    { kind: "my-runs" }, // admin sees "All runs" via ALL_RUNS_ROLES
    { kind: "run-lifecycle" },
  ],
  lead: [
    { kind: "scenarios" },
    { kind: "my-runs" }, // lead sees "All runs" via ALL_RUNS_ROLES
    { kind: "run-lifecycle" },
  ],
  red: [
    { kind: "scenarios" },
    { kind: "my-runs" },
    { kind: "run-lifecycle" },
  ],
  blue: [
    { kind: "scenarios" },
    { kind: "my-runs" },
    // blue is read-only — no RunLifecycleCard.
  ],
  observer: [
    { kind: "scenarios" },
    { kind: "my-runs" }, // observer sees "All runs" via ALL_RUNS_ROLES
    // observer cannot start — no RunLifecycleCard.
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

        {pickedScenario && (
          <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            Loaded scenario:{" "}
            <span className="font-mono">{pickedScenario.name}</span>{" "}
            (id={pickedScenario.id}). Half 2 will plug the
            RunInspectorCard here for full detail + audit + assets.
          </div>
        )}
      </main>
    </div>
  );
}
