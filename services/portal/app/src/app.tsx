import { useEffect, useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { MyRunsCard, type RunRow } from "@/components/portal/my-runs-card";
import { RunLifecycleCard } from "@/components/portal/run-lifecycle-card";
import { PveOpsCard } from "@/components/portal/pve-ops-card";
import { ScenarioAuthoringCard } from "@/components/portal/scenario-authoring-card";
import { SignInCard } from "@/components/portal/sign-in-card";
import { OnboardingWizard } from "@/components/portal/onboarding-wizard";
import { TopNav, type ViewKey } from "@/components/portal/top-nav";
import { DashboardCard } from "@/components/portal/dashboard-card";
import { DrillConsole } from "@/components/portal/drill-console";
import { OperatorConsoleCard } from "@/components/portal/operator-console-card";
import { ProfileCard } from "@/components/portal/profile-card";
import { UserListCard } from "@/components/portal/user-list-card";
import { ToastHost } from "@/components/portal/toast";
import { useHashRoute } from "@/hooks/use-hash-route";
import { useMe } from "@/lib/auth";
import { probeSetup } from "@/lib/api";

/**
 * Top-level portal layout.
 *
 * F4-UI: cyber-range portal v2. The previous layout was a vertical
 * stack of all cards for the current role. Real cyber-range
 * platforms (TryHackMe, HackTheBox, RangeForce, Immersive Labs,
 * CyLab/picoCTF) organise the UI around view tabs: Dashboard,
 * Operate (start a drill), Observe (watch a live drill), Admin
 * (platform ops), History (past runs), Profile (your stats).
 *
 * Tab visibility is derived from the role via the same matrix
 * the card composition used:
 *
 *   * anonymous → SignInCard (returning deployment) or
 *                 OnboardingWizard (empty deployment). Determined
 *                 on mount by GET /api/v1/auth/setup probe.
 *   * admin/lead → all tabs.
 *   * red/blue/observer → no Admin tab.
 *
 * Hash routing (no react-router): the URL hash is the active view.
 * `window.location.hash = "#/operate"` switches view. The hook
 * subscribes to hashchange so back/forward buttons work.
 *
 * Sign-in UX (F-signin-ux):
 *   On mount, when no token exists, we probe GET /api/v1/auth/setup.
 *   - needs_setup=false → SignInCard (returning operator, admin exists)
 *   - needs_setup=true  → OnboardingWizard (first-time deploy)
 *   - probe error       → SignInCard (safe fallback; wizard link at bottom)
 *   This mirrors TryHackMe / HackTheBox: sign-in is the default landing
 *   page. First-time setup is discovered only when the DB is empty.
 */

const VALID_VIEWS = [
  "dashboard",
  "operate",
  "observe",
  "admin",
  "history",
  "profile",
] as const;

// Three states for the anonymous landing:
//   "probing"  — waiting for GET /api/v1/auth/setup
//   "signin"   — show SignInCard  (needs_setup=false or probe error)
//   "wizard"   — show OnboardingWizard (needs_setup=true)
type AnonView = "probing" | "signin" | "wizard";

export default function App() {
  const [pickedScenario, setPickedScenario] = useState<Scenario | null>(null);
  const [pickedRun, setPickedRun] = useState<RunRow | null>(null);
  const { me, loading } = useMe();
  const [activeView, setActiveView] = useHashRoute(VALID_VIEWS, "dashboard");

  // F-signin-ux: probe on mount so returning operators land on the
  // sign-in form immediately instead of digging through the wizard.
  const [anonView, setAnonView] = useState<AnonView>("probing");

  useEffect(() => {
    // Only probe when there's no token (me===null after useMe settles).
    // We can't wait for `loading` to finish before starting the probe —
    // fire it immediately and let them race; the faster one wins.
    let cancelled = false;
    probeSetup()
      .then(({ needs_setup }) => {
        if (!cancelled) setAnonView(needs_setup ? "wizard" : "signin");
      })
      .catch(() => {
        // Probe failed (API down, network error). Fall back to SignInCard.
        // The wizard link at the bottom lets first-timers escape.
        if (!cancelled) setAnonView("signin");
      });
    return () => { cancelled = true; };
  }, []);

  function onPickRunFromDashboard(runId: number) {
    // The Dashboard's "Recent runs" list jumps the operator
    // directly into Observe for that run.
    const fake: RunRow = {
      id: runId,
      scenario_id: pickedScenario?.id,
      status: "unknown",
    };
    setPickedRun(fake);
    setActiveView("observe");
  }

  return (
    <ToastHost>
    <div className="min-h-screen bg-background">
      <TopNav activeView={activeView} onChangeView={setActiveView} />
      <main className="container mx-auto max-w-6xl space-y-6 px-4 py-8">
        {/* ── anonymous user landing ────────────────────────────────────
             Three states driven by the setup probe result:
             "probing" → spinner while GET /api/v1/auth/setup is in-flight
             "signin"  → SignInCard (returning deployment, admin exists)
             "wizard"  → OnboardingWizard (empty deployment, needs setup)
             me===null && loading  → useMe still resolving (/me in-flight)
        ─────────────────────────────────────────────────────────────── */}
        {!me && (loading || anonView === "probing") && (
          <p className="text-sm italic text-muted-foreground">
            Identifying…
          </p>
        )}
        {!me && !loading && anonView === "signin" && (
          // F-signin-ux: returning deployment. Admin exists — show
          // the sign-in form directly, no wizard in the way.
          <SignInCard
            onNeedsSetup={() => setAnonView("wizard")}
            onSignedIn={(nextView) => {
              // F-auth-ux (Plan A4): preserve deep-link across
              // sign-out → sign-in. setActiveView calls the hash-
              // router, which writes window.location.hash.
              if (nextView && VALID_VIEWS.includes(nextView as ViewKey)) {
                setActiveView(nextView as ViewKey);
              }
            }}
          />
        )}
        {!me && !loading && anonView === "wizard" && (
          // F10.3: empty deployment. Guide the operator through
          // creating the first admin + launching their first drill.
          <OnboardingWizard
            onLaunched={(runId) => {
              setPickedRun({
                id: runId,
                status: "unknown",
              });
              setActiveView("observe");
            }}
            onSignInInstead={() => setAnonView("signin")}
          />
        )}
        {me &&
          (() => {
            switch (activeView) {
              case "dashboard":
                return (
                  <DashboardCard
                    meRole={me.role}
                    meSub={me.sub}
                    onPickRun={onPickRunFromDashboard}
                  />
                );
              case "operate":
                return (
                  <>
                    <ScenariosCard
                      pickedId={pickedScenario?.id ?? null}
                      onPick={setPickedScenario}
                    />
                    <RunLifecycleCard
                      meSub={me.sub}
                      meRole={me.role}
                      scenario={pickedScenario}
                      pickedRunId={pickedRun?.id ?? null}
                    />
                    <MyRunsCard
                      meRole={me.role}
                      pickedRunId={pickedRun?.id ?? null}
                      onPick={setPickedRun}
                    />
                  </>
                );
              case "observe":
                return (
                  <DrillConsole
                    pickedRunId={pickedRun?.id ?? null}
                    scenarioName={pickedScenario?.title ?? pickedScenario?.name}
                  />
                );
              case "admin":
                return (
                  <>
                    <OperatorConsoleCard />
                    <PveOpsCard />
                    <ScenarioAuthoringCard />
                    <UserListCard />
                  </>
                );
              case "history":
                return (
                  <MyRunsCard
                    meRole={me.role}
                    pickedRunId={pickedRun?.id ?? null}
                    onPick={setPickedRun}
                  />
                );
              case "profile":
                return <ProfileCard meRole={me.role} meSub={me.sub} />;
              default: {
                const _exhaustive: never = activeView;
                void _exhaustive;
                return null;
              }
            }
          })()}
      </main>
    </div>
    </ToastHost>
  );
}
