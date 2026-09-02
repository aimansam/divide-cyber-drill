import { useEffect, useState } from "react";
import { ScenariosCard, type Scenario } from "@/components/portal/scenarios-card";
import { MyRunsCard, type RunRow } from "@/components/portal/my-runs-card";
import { RunLifecycleCard } from "@/components/portal/run-lifecycle-card";
import { PveOpsCard } from "@/components/portal/pve-ops-card";
import { ConfigCard } from "@/components/portal/config-card";
import { ScenarioAuthoringCard } from "@/components/portal/scenario-authoring-card";
import { SignInCard } from "@/components/portal/sign-in-card";
import { ResetPasswordCard } from "@/components/portal/reset-password-card";
import { OnboardingWizard } from "@/components/portal/onboarding-wizard";
import { TopNav, type ViewKey } from "@/components/portal/top-nav";
import { CommandCenterCard } from "@/components/portal/command-center-card";
import { DrillConsole } from "@/components/portal/drill-console";
import { OperatorConsoleCard } from "@/components/portal/operator-console-card";
import { GlobalAuditCard } from "@/components/portal/global-audit-card";
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
 *   * anonymous + URL has ?sub=&token= → ResetPasswordCard
 *                                           (F-reset-ux: clicked
 *                                           a magic link)
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
 *
 * Password reset UX (F-reset-ux):
 *   Magic links arrive as /portal/app/#/?sub=<sub>&token=<token>.
 *   On render we read the URL hash; if both sub + token are
 *   present, we mount ResetPasswordCard instead of SignInCard
 *   (the sign-in card's normal flow takes a back seat). On a
 *   successful reset the card clears the hash and lands on the
 *   regular sign-in form.
 */

const VALID_VIEWS = [
  "dashboard",
  "operate",
  "observe",
  "admin",
  "config",
  "history",
  "profile",
] as const;

// Three states for the anonymous landing:
//   "probing"  — waiting for GET /api/v1/auth/setup
//   "signin"   — show SignInCard  (needs_setup=false or probe error)
//   "wizard"   — show OnboardingWizard (needs_setup=true)
type AnonView = "probing" | "signin" | "wizard";

// F-reset-ux: parse a magic-link URL into the (sub, token) pair.
// The URL format is ``/portal/app/#/?sub=<sub>&token=<token>`` --
// the query string lives in the URL fragment because we use a
// hash-based router. Returning ``null`` if either is missing.
function readResetParamsFromHash(): { sub: string; token: string } | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  // ``/#/...?sub=foo&token=bar`` -> fragment is ``/?sub=foo&token=bar``.
  const qIndex = hash.indexOf("?");
  if (qIndex === -1) return null;
  const params = new URLSearchParams(hash.slice(qIndex + 1));
  const sub = params.get("sub");
  const token = params.get("token");
  if (!sub || !token) return null;
  return { sub, token };
}

export default function App() {
  const [pickedScenario, setPickedScenario] = useState<Scenario | null>(null);
  const [pickedRun, setPickedRun] = useState<RunRow | null>(null);
  const { me, loading } = useMe();
  const [activeView, setActiveView] = useHashRoute(VALID_VIEWS, "dashboard");

  // F-signin-ux: probe on mount so returning operators land on the
  // sign-in form immediately instead of digging through the wizard.
  const [anonView, setAnonView] = useState<AnonView>("probing");

  // F-reset-ux: read magic-link params from the URL hash on mount
  // and on hashchange. If present, the app renders ResetPasswordCard
  // regardless of probe state -- the user clicked a reset link,
  // so we want them to land on the reset form immediately.
  const [resetParams, setResetParams] = useState(() =>
    readResetParamsFromHash(),
  );

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

  // F-reset-ux: re-read magic-link params on hashchange. The hash
  // can be mutated externally (e.g. by another script clearing it
  // after a successful reset) so we keep state in sync with the URL.
  useEffect(() => {
    function onHashChange() {
      setResetParams(readResetParamsFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // F-reset-ux: clear the hash after a successful reset. We keep
  // the SignInCard mount path the same so the user lands on the
  // sign-in form to type their new password.
  function onResetComplete() {
    // Strip the query string but keep the hash router happy
    // (a bare ``#/`` keeps the active view at "dashboard").
    window.location.hash = "#/";
    setResetParams(null);
  }

  function onPickRunFromDashboard(runId: number) {
    // Q27: kept for backward compatibility but no longer used by CommandCenterCard.
    // The Command Center passes the full run row to onPickRun.
    const fake: RunRow = {
      run_id: runId,
      scenario_id: pickedScenario?.id,
      status: "unknown",
    };
    setPickedRun(fake);
    setActiveView("observe");
  }
  void onPickRunFromDashboard; // suppress unused warning

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
        {!me && (loading || anonView === "probing") && !resetParams && (
          <p className="text-sm italic text-muted-foreground">
            Identifying…
          </p>
        )}
        {!me && !loading && resetParams && (
          // F-reset-ux: user clicked a magic link. Render the reset
          // card regardless of probe state -- they came in via a
          // direct URL, not the normal landing path. ``anonView``
          // is irrelevant here.
          <ResetPasswordCard
            sub={resetParams.sub}
            token={resetParams.token}
            onReset={onResetComplete}
          />
        )}
        {!me && !loading && anonView === "signin" && !resetParams && (
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
        {!me && !loading && anonView === "wizard" && !resetParams && (
          // F10.3: empty deployment. Guide the operator through
          // creating the first admin + launching their first drill.
          <OnboardingWizard
            onLaunched={(runId) => {
              setPickedRun({
                run_id: runId,
                status: "unknown",
              });
              setActiveView("observe");
            }}
            onNavigateToConfig={() => setActiveView("config")}
          />
        )}
        {me &&
          (() => {
            switch (activeView) {
              case "dashboard":
                return (
                  <CommandCenterCard
                    meRole={me.role}
                    meSub={me.sub}
                    onNavigate={(view) => setActiveView(view)}
                    onPickRun={(run) => {
                      setPickedRun({ run_id: run.run_id, status: run.status });
                      setActiveView("observe");
                    }}
                  />
                );
              case "operate":
                return (
                  <div className="grid grid-cols-1 gap-6 lg:grid-cols-[380px_1fr] items-start">
                    <div className="lg:sticky lg:top-4">
                      <ScenariosCard
                        pickedId={pickedScenario?.id ?? null}
                        onPick={setPickedScenario}
                      />
                    </div>
                    <RunLifecycleCard
                      meSub={me.sub}
                      meRole={me.role}
                      scenario={pickedScenario}
                      pickedRunId={pickedRun?.run_id ?? null}
                      onNavigateToConfig={() => setActiveView("config")}
                      onNavigateToObserve={(runId) => {
                        setPickedRun({ run_id: runId, status: "running" });
                        setActiveView("observe");
                      }}
                    />
                  </div>
                );
              case "observe":
                return (
                  <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr] items-start">
                    <div className="lg:sticky lg:top-4">
                      <MyRunsCard
                        meRole={me.role}
                        pickedRunId={pickedRun?.run_id ?? null}
                        onPick={setPickedRun}
                        compact
                        liveOnly
                      />
                    </div>
                    <DrillConsole
                      pickedRunId={pickedRun?.run_id ?? null}
                      scenarioName={pickedScenario?.title ?? pickedScenario?.name}
                    />
                  </div>
                );
              case "admin":
                return (
                  <>
                    <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                      <OperatorConsoleCard
                        onNavigateToObserve={(runId) => {
                          setPickedRun({ run_id: runId, status: "running" });
                          setActiveView("observe");
                        }}
                      />
                      <PveOpsCard />
                    </div>
                    {/* Q21: cross-run audit search. Pinned at the top
                        of the admin tab so it doesn't get buried
                        below the longer scenario + user CRUD cards. */}
                    <GlobalAuditCard />
                    <ScenarioAuthoringCard />
                    <UserListCard />
                  </>
                );
              case "config":
                return (
                  <ConfigCard
                    meRole={me.role}
                    onNavigateToView={(v) => setActiveView(v)}
                  />
                );
              case "history":
                return (
                  <MyRunsCard
                    meRole={me.role}
                    pickedRunId={pickedRun?.run_id ?? null}
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
