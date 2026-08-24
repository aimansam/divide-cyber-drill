import { useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { TokenBar } from "@/components/portal/token-bar";
import { MyRunsCard, type RunRow } from "@/components/portal/my-runs-card";
import { RunLifecycleCard } from "@/components/portal/run-lifecycle-card";
import { PveOpsCard } from "@/components/portal/pve-ops-card";
import { ScenarioAuthoringCard } from "@/components/portal/scenario-authoring-card";
import { SignInCard } from "@/components/portal/sign-in-card";
import { TopNav } from "@/components/portal/top-nav";
import { DashboardCard } from "@/components/portal/dashboard-card";
import { DrillConsole } from "@/components/portal/drill-console";
import { useHashRoute } from "@/hooks/use-hash-route";
import { useMe } from "@/lib/auth";

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
 *   * anonymous → only the SignInCard is shown; no tabs render.
 *   * admin/lead → all tabs.
 *   * red/blue/observer → no Admin tab.
 *
 * Hash routing (no react-router): the URL hash is the active view.
 * `window.location.hash = "#/operate"` switches view. The hook
 * subscribes to hashchange so back/forward buttons work.
 *
 * The anonymous / SignInCard path is intentionally below the
 * TopNav so a signed-out user still sees the brand bar — that's
 * the entry point that tells them what they're logging into.
 */

const VALID_VIEWS = [
  "dashboard",
  "operate",
  "observe",
  "admin",
  "history",
  "profile",
] as const;

export default function App() {
  const [pickedScenario, setPickedScenario] = useState<Scenario | null>(null);
  const [pickedRun, setPickedRun] = useState<RunRow | null>(null);
  const { me, loading } = useMe();
  const [activeView, setActiveView] = useHashRoute(VALID_VIEWS, "dashboard");

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
    <div className="min-h-screen bg-background">
      <TopNav activeView={activeView} onChangeView={setActiveView} />
      <main className="container mx-auto max-w-6xl space-y-6 px-4 py-8">
        {!me && loading && (
          <p className="text-sm italic text-muted-foreground">
            Identifying…
          </p>
        )}
        {!me && !loading && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Sign in to operate drills, observe live exercises, and
              download after-action reports.
            </p>
            <SignInCard />
          </div>
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
                    <PveOpsCard />
                    <ScenarioAuthoringCard />
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
                return (
                  <DashboardCard
                    meRole={me.role}
                    meSub={me.sub}
                    onPickRun={onPickRunFromDashboard}
                  />
                );
              default: {
                const _exhaustive: never = activeView;
                void _exhaustive;
                return null;
              }
            }
          })()}
      </main>
      <TokenBar />
    </div>
  );
}
