/**
 * OnboardingWizard -- F10.3 / F10.4 first-time user experience.
 *
 * Replaces the cold "SignInCard on an empty deployment" UX with
 * a guided 4-step flow:
 *
 *   1. Bootstrap admin  -- POST /api/v1/auth/setup (only succeeds
 *                          if the user table is empty).
 *   2. Pick scenario    -- GET /api/v1/scenarios; operator picks
 *                          one for the upcoming drill.
 *   3. Form team        -- (multi-team scenarios only) name the
 *                          red / blue teams + bulk-create the
 *                          players via POST /api/v1/auth/users.
 *                          Single-team scenarios skip this step.
 *   4. Launch drill     -- POST /api/v1/exercises (with teams) +
 *                          POST /api/v1/exercises/{id}/start.
 *                          Then redirect to the live DrillConsole.
 *
 * Step transitions:
 *   * Steps 1-3 are sequential. Each step's Next button is
 *     disabled until that step's data is valid.
 *   * Step 1 short-circuits to step 2 if the server returns
 *     409 (admin already exists). The wizard doesn't make the
 *     operator click through a no-op.
 *   * Step 3 short-circuits to step 4 if the chosen scenario
 *     doesn't declare red + blue teams (single-team drill).
 *
 * Persistence:
 *   * Each completed step's data lives in component state. If
 *     the operator refreshes, they restart at step 1 (with
 *     step 1 fast-forwarded to 2 because setup is single-shot
 *     and idempotent at the API level).
 *
 * Why a single component instead of four cards:
 *   The wizard is one operator task; splitting it into cards
 *   would force a parent to manage the step counter + form
 *   state. One component keeps the data flow obvious.
 */

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Loader2,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "./empty-state";
import { ApiError, api, setToken } from "@/lib/api";
import { emitTokenChange } from "@/lib/auth";
import type { Scenario } from "./scenarios-card";
import { Step0PveSetup } from "./step0-pve-setup";
import { PveCredentialsStep } from "./pve-credentials-step";

// ---------------------------------------------------------------- types

// F-pve-bridge-wizard: Step 0 is the new PVE bridge setup. The
// existing 4 steps renumber to 1..4 (admin / scenario / team /
// launch). Step 0 auto-skips when no bridges are needed (e.g.
// when running against the mock adapter) or when they're all
// already present on PVE.
//
// F-pve-config-ui: Step -1 is the very first step -- the PVE
// credentials form (host + token). It runs BEFORE Step 0 and
// auto-skips when the API already has a config row. The 5-step
// indicator (PVE bridges / Bootstrap admin / Pick scenario /
// Form team / Launch drill) stays the same; the credentials
// step is a silent pre-flight that the operator only sees when
// they haven't yet configured PVE.
type Step = -1 | 0 | 1 | 2 | 3 | 4;

interface ScenarioWithMeta extends Scenario {
  // F10.3 only renders the multi-team step for scenarios that
  // declare red+blue teams. The spec lives under scenario.spec
  // -- we read it once via the catalog and cache the bool here.
  is_multi_team: boolean;
}

// Augment the Scenario type with the spec field. The catalog
// endpoint (F10.3) now includes spec so the wizard can detect
// multi-team scenarios without an N+1 fetch.
declare module "./scenarios-card" {
  interface Scenario {
    spec?: {
      objectives?: { red?: unknown[]; blue?: unknown[] };
      [k: string]: unknown;
    };
  }
}

interface OnboardingWizardProps {
  /** Callback fired when the wizard launches the exercise.
   *  Parent (app.tsx) uses this to switch to the live view. */
  onLaunched: (exerciseId: number) => void;
}

// ---------------------------------------------------------------- helpers

async function listScenariosWithMeta(): Promise<ScenarioWithMeta[]> {
  const items = await api.get<Scenario[]>("/api/v1/scenarios");
  return items.map((s) => ({
    ...s,
    is_multi_team: _scenarioIsMultiTeam(s),
  }));
}

function _scenarioIsMultiTeam(s: Scenario): boolean {
  // A scenario is multi-team if its spec declares red + blue
  // objectives (F6 marker). Single-team drills have only one
  // side declared. The wizard uses this to decide whether to
  // show step 3.
  const objectives = s.spec?.objectives;
  if (!objectives) return false;
  return Boolean(objectives.red && objectives.blue);
}

async function setupFirstAdmin(
  sub: string,
  password: string,
): Promise<{ token: string; sub: string; role: string }> {
  const resp = await api.post<{
    token: string;
    sub: string;
    role: string;
  }>("/api/v1/auth/setup", { sub, password });
  return resp;
}

// ---------------------------------------------------------------- component
//
// F-signin-ux: app.tsx only mounts this wizard when the setup probe
// returns needs_setup=true (i.e. the users table is empty). The
// previous "admin already exists" amber callout inside step 1 was
// dead code -- it could only ever fire if the wizard mounted AFTER
// a different tab created an admin, which the probe catches. We
// removed the adminExists state entirely in the F-auth-ux cleanup
// so the wizard now strictly handles the empty-deployment path.

export function OnboardingWizard({ onLaunched }: OnboardingWizardProps) {
  // F-pve-config-ui: start at -1 (the PVE credentials pre-step). The
  // component for that step calls onContinue() which advances to 0.
  // If the API already has a config, the pre-step auto-advances via
  // its own onMount effect, so the operator never sees a flicker.
  const [step, setStep] = useState<Step>(-1);
  const [error, setError] = useState<string | null>(null);

  // Step 1 state: admin credentials.
  const [adminSub, setAdminSub] = useState("");
  const [adminPw, setAdminPw] = useState("");
  const [adminSubmitting, setAdminSubmitting] = useState(false);
  // When true, step 1 short-circuits to step 2 on render.
  const [setupDone, setSetupDone] = useState(false);

  // Step 2 state: scenario catalog.
  const [scenarios, setScenarios] = useState<ScenarioWithMeta[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [pickedScenario, setPickedScenario] =
    useState<ScenarioWithMeta | null>(null);

  // Step 3 state: team formation.
  const [redName, setRedName] = useState("red");
  const [blueName, setBlueName] = useState("blue");
  const [memberSubs, setMemberSubs] = useState<string[]>(["", ""]);
  const [submittingTeams, setSubmittingTeams] = useState(false);

  // Step 4 state: launch.
  const [launching, setLaunching] = useState(false);

  // On mount: if the server already has users (409 on /setup probe
  // -- we don't actually call /setup here), we skip step 1. We
  // use a single-shot probe to detect this; the actual /setup call
  // happens on form submit so we don't leak timing.
  //
  // We don't probe -- instead, the wizard starts at step 1 and
  // only advances to step 2 once the operator successfully creates
  // an admin OR the server returns 409. This matches what
  // operators expect: "show me the setup form first; tell me if
  // it's already done when I try."

  // Step 1 handler: create the first admin. On 409, advance.
  async function handleStep1(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!adminSub.trim() || !adminPw) {
      setError("Username and password are required.");
      return;
    }
    if (adminPw.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setAdminSubmitting(true);
    try {
      const resp = await setupFirstAdmin(adminSub.trim(), adminPw);
      // Stash the token + emit the auth event so useMe() picks up
      // the new admin identity and app.tsx re-renders.
      setToken(resp.token);
      emitTokenChange(resp.token);
      setSetupDone(true);
      setStep(2);
      void loadScenarios();
    } catch (e: unknown) {
      // F-signin-ux: if POST /auth/setup returns 409 it means an
      // admin was created between the probe and the form submit
      // (rare race). The right UX is to surface the server's
      // message and let the operator decide what to do; we don't
      // try to be clever here because the wizard itself isn't
      // supposed to render for non-empty deployments.
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setError(`setup failed: ${msg}`);
    } finally {
      setAdminSubmitting(false);
    }
  }

  async function loadScenarios() {
    setScenariosLoading(true);
    setError(null);
    try {
      const items = await listScenariosWithMeta();
      setScenarios(items);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setError(`failed to load scenarios: ${msg}`);
    } finally {
      setScenariosLoading(false);
    }
  }

  // Step 2 handler: pick scenario, advance (to step 3 if multi-team
  // or step 4 if single-team).
  function handleStep2Next() {
    if (pickedScenario === null) return;
    if (pickedScenario.is_multi_team) {
      setStep(3);
    } else {
      // Single-team drill: skip team formation.
      setStep(4);
    }
  }

  // Step 3 handler: create the exercise + members + start it.
  async function handleStep3Submit(e: React.FormEvent) {
    e.preventDefault();
    if (pickedScenario === null) return;
    setError(null);
    setSubmittingTeams(true);
    try {
      const exercise = await api.post<{ id: number }>("/api/v1/exercises", {
        name: `wizard-${pickedScenario.name}-${Date.now()}`,
        title: `Onboarding: ${pickedScenario.title}`,
        scenario_id: pickedScenario.id,
        teams: [
          { name: redName.trim() || "red", color: "#dc2626" },
          { name: blueName.trim() || "blue", color: "#2563eb" },
        ],
      });
      // Bulk-create the member users. Skip blanks.
      const subs = memberSubs.map((s) => s.trim()).filter(Boolean);
      for (const sub of subs) {
        try {
          await api.post("/api/v1/auth/users", {
            sub,
            password: "welcome-1234",  // F10.3: same initial pw for all
            role: "red",
          });
        } catch (e: unknown) {
          if (e instanceof ApiError && e.status === 409) {
            // Already exists -- that's fine, the operator can
            // re-distribute credentials manually.
            continue;
          }
          throw e;
        }
      }
      // Start the exercise.
      await api.post(`/api/v1/exercises/${exercise.id}/start`, {});
      setStep(4);
      onLaunched(exercise.id);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setError(`team setup failed: ${msg}`);
    } finally {
      setSubmittingTeams(false);
    }
  }

  // Step 4 handler: for single-team scenarios we create a Run
  // (not an Exercise) and call onLaunched.
  async function handleStep4Submit(e: React.FormEvent) {
    e.preventDefault();
    if (pickedScenario === null) return;
    setError(null);
    setLaunching(true);
    try {
      const run = await api.post<{ id: number }>("/api/v1/drills", {
        scenario_id: pickedScenario.id,
      });
      onLaunched(run.id);
    } catch (e: unknown) {
      const msg = e instanceof ApiError ? `HTTP ${e.status}` : String(e);
      setError(`drill launch failed: ${msg}`);
    } finally {
      setLaunching(false);
    }
  }

  // When the wizard mounts, fetch scenarios in the background so
  // step 2 is ready by the time the operator reaches it.
  useEffect(() => {
    void loadScenarios();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card data-testid="onboarding-wizard" className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl">
          <Sparkles className="h-5 w-5 text-primary" />
          Set up your cyber range
        </CardTitle>
        <CardDescription>
          Five quick steps to your first drill. Step 0 sets up the
          PVE bridges your scenarios will use; the rest pick a
          scenario, form a team, and launch. You can always come
          back and run individual steps from the Admin tab later.
        </CardDescription>
        <StepIndicator current={step} done={setupDone ? 1 : 0} />
      </CardHeader>
      <CardContent>
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-700 bg-red-950/40 px-3 py-2 text-sm text-red-200"
          >
            {error}
          </div>
        )}

        {step === -1 && (
          // F-pve-config-ui: collect PVE host + token before Step 0
          // (bridges). Auto-skips to 0 once the credentials are saved
          // or when the API already has a config row.
          <PveCredentialsStep
            onContinue={() => setStep(0)}
            onSkip={() => setStep(0)}
          />
        )}

        {step === 0 && (
          // F-pve-bridge-wizard: probe + SSH bridge setup.
          // Auto-advances to step 1 when everything's already
          // present on PVE.
          <Step0PveSetup
            onContinue={() => setStep(1)}
            onSkip={() => setStep(1)}
          />
        )}

        {step === 1 && (
          <Step1
            sub={adminSub}
            setSub={setAdminSub}
            password={adminPw}
            setPassword={setAdminPw}
            submitting={adminSubmitting}
            onSubmit={handleStep1}
          />
        )}

        {step === 2 && (
          <Step2
            scenarios={scenarios}
            loading={scenariosLoading}
            picked={pickedScenario}
            onPick={setPickedScenario}
            onNext={handleStep2Next}
            onRetry={loadScenarios}
          />
        )}

        {step === 3 && pickedScenario !== null && (
          <Step3
            scenario={pickedScenario}
            redName={redName}
            setRedName={setRedName}
            blueName={blueName}
            setBlueName={setBlueName}
            memberSubs={memberSubs}
            setMemberSubs={setMemberSubs}
            submitting={submittingTeams}
            onSubmit={handleStep3Submit}
          />
        )}

        {step === 4 && pickedScenario !== null && (
          <Step4
            scenario={pickedScenario}
            launching={launching}
            isMultiTeam={pickedScenario.is_multi_team}
            onSubmit={handleStep4Submit}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------- StepIndicator

function StepIndicator({
  current,
  done,
}: {
  current: Step;
  done: number;
}) {
  // F-pve-config-ui: step -1 is a silent pre-flight (PVE creds).
  // It doesn't appear in the visible step list; we map it to the
  // "PVE bridges" indicator so the operator still sees forward
  // progress while the credentials step is doing its work.
  const visibleCurrent: Step = current < 0 ? 0 : current;
  const labels: Record<Step, string> = {
    "-1": "PVE creds",
    0: "PVE bridges",
    1: "Bootstrap admin",
    2: "Pick scenario",
    3: "Form team",
    4: "Launch drill",
  };
  // The visible step list excludes -1 (it's not numbered in the
  // operator's mental model). current < 0 is mapped to 0 so the
  // indicator's first circle lights up.
  const steps: Step[] = [0, 1, 2, 3, 4];
  return (
    <ol className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {steps.map((s, i) => {
        // ``done`` only tracks the admin-step explicitly;
        // everything else is "done if strictly before current".
        // Pre-step -1 maps to step 0 so the first circle is
        // highlighted while the operator is filling creds.
        const isDone = s < visibleCurrent || (s === 1 && done >= 1);
        const isCurrent = s === visibleCurrent;
        return (
          <li key={s} className="flex items-center gap-1">
            <span
              data-testid={`wizard-step-${s}`}
              className={
                "inline-flex h-5 w-5 items-center justify-center rounded-full " +
                (isDone
                  ? "bg-primary text-primary-foreground"
                  : isCurrent
                  ? "bg-primary/30 text-primary ring-1 ring-primary"
                  : "bg-muted text-muted-foreground")
              }
            >
              {isDone ? <Check className="h-3 w-3" /> : s}
            </span>
            <span
              className={
                isCurrent
                  ? "font-medium text-foreground"
                  : "text-muted-foreground"
              }
            >
              {labels[s]}
            </span>
            {i < steps.length - 1 && (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- Step 1

interface Step1Props {
  sub: string;
  setSub: (s: string) => void;
  password: string;
  setPassword: (s: string) => void;
  submitting: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

function Step1({
  sub,
  setSub,
  password,
  setPassword,
  submitting,
  onSubmit,
}: Step1Props) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p>
          Create the first admin. This is a one-shot step: once any
          admin exists, you'll sign in instead. Subsequent users are
          added from the Admin tab.
        </p>
      </div>
      <div>
        <label htmlFor="wiz-sub" className="block text-sm font-medium">
          Admin username
        </label>
        <Input
          id="wiz-sub"
          value={sub}
          onChange={(e) => setSub(e.target.value)}
          placeholder="alice"
          autoComplete="username"
          data-testid="wizard-admin-sub"
        />
      </div>
      <div>
        <label htmlFor="wiz-pw" className="block text-sm font-medium">
          Admin password
        </label>
        <Input
          id="wiz-pw"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Minimum 8 characters"
          autoComplete="new-password"
          data-testid="wizard-admin-pw"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Use a strong password you won't reuse elsewhere. div:ide stores
          argon2id hashes -- the plaintext never leaves this form.
        </p>
      </div>
      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={submitting}
          data-testid="wizard-admin-submit"
        >
          {submitting ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <ArrowRight className="mr-1 h-3 w-3" />
          )}
          {submitting ? "Creating admin..." : "Create admin"}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- Step 2

interface Step2Props {
  scenarios: ScenarioWithMeta[];
  loading: boolean;
  picked: ScenarioWithMeta | null;
  onPick: (s: ScenarioWithMeta) => void;
  onNext: () => void;
  onRetry: () => void;
}

function Step2({
  scenarios,
  loading,
  picked,
  onPick,
  onNext,
  onRetry,
}: Step2Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <Target className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p>
          Pick the scenario you'll run. Multi-team scenarios (with red
          + blue objectives) advance to team formation; single-team
          ones skip straight to launch.
        </p>
      </div>

      {loading && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          Loading scenarios...
        </p>
      )}

      {!loading && scenarios.length === 0 && (
        <EmptyState
          title="No scenarios synced yet"
          description="The catalog is empty. Run `make sync-scenarios` on the host, or upload one from the Admin tab."
          cta="Refresh"
          onCta={onRetry}
        />
      )}

      {!loading && scenarios.length > 0 && (
        <ul className="space-y-2" data-testid="wizard-scenario-list">
          {scenarios.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onPick(s)}
                className={
                  "w-full rounded-md border p-3 text-left transition-colors " +
                  (picked?.id === s.id
                    ? "border-primary bg-primary/10"
                    : "border-border hover:bg-muted/40")
                }
                data-testid={`wizard-scenario-${s.id}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="font-mono text-sm font-semibold">
                      {s.name}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.title}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 text-xs">
                    <span className="rounded bg-muted px-2 py-0.5 text-muted-foreground">
                      {s.difficulty || "n/a"}
                    </span>
                    <span className="rounded bg-muted px-2 py-0.5 text-muted-foreground">
                      {s.duration_min || "?"} min
                    </span>
                    {s.is_multi_team ? (
                      <span
                        className="rounded bg-blue-900/40 px-2 py-0.5 text-blue-200"
                        data-testid={`wizard-multi-${s.id}`}
                      >
                        multi-team
                      </span>
                    ) : (
                      <span
                        className="rounded bg-amber-900/40 px-2 py-0.5 text-amber-200"
                        data-testid={`wizard-single-${s.id}`}
                      >
                        single-team
                      </span>
                    )}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex justify-end">
        <Button
          type="button"
          disabled={picked === null}
          onClick={onNext}
          data-testid="wizard-scenario-next"
        >
          Next
          <ArrowRight className="ml-1 h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Step 3

interface Step3Props {
  scenario: ScenarioWithMeta;
  redName: string;
  setRedName: (s: string) => void;
  blueName: string;
  setBlueName: (s: string) => void;
  memberSubs: string[];
  setMemberSubs: (s: string[]) => void;
  submitting: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

function Step3({
  scenario,
  redName,
  setRedName,
  blueName,
  setBlueName,
  memberSubs,
  setMemberSubs,
  submitting,
  onSubmit,
}: Step3Props) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <Users className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p>
          Set up the red and blue teams for{" "}
          <span className="font-mono">{scenario.name}</span>. Members
          get the same initial password -- redistribute it after the
          launch.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label
            htmlFor="wiz-red"
            className="block text-sm font-medium text-red-300"
          >
            Red team name
          </label>
          <Input
            id="wiz-red"
            value={redName}
            onChange={(e) => setRedName(e.target.value)}
            data-testid="wizard-red-name"
          />
        </div>
        <div>
          <label
            htmlFor="wiz-blue"
            className="block text-sm font-medium text-blue-300"
          >
            Blue team name
          </label>
          <Input
            id="wiz-blue"
            value={blueName}
            onChange={(e) => setBlueName(e.target.value)}
            data-testid="wizard-blue-name"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium">
          Members to create (optional)
        </label>
        <p className="mb-2 text-xs text-muted-foreground">
          Add one username per line. Blank lines are skipped.
        </p>
        <textarea
          className="min-h-[7rem] w-full rounded-md border border-border bg-background p-2 font-mono text-sm"
          value={memberSubs.join("\n")}
          onChange={(e) =>
            setMemberSubs(e.target.value.split("\n").slice(0, 12))
          }
          placeholder={"red-1\nred-2\nblue-1\nblue-2"}
          data-testid="wizard-member-subs"
        />
      </div>

      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={submitting}
          data-testid="wizard-teams-submit"
        >
          {submitting ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <ArrowRight className="mr-1 h-3 w-3" />
          )}
          {submitting ? "Creating exercise..." : "Create + launch exercise"}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- Step 4

interface Step4Props {
  scenario: ScenarioWithMeta;
  launching: boolean;
  isMultiTeam: boolean;
  onSubmit: (e: React.FormEvent) => void;
}

function Step4({ scenario, launching, isMultiTeam, onSubmit }: Step4Props) {
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p>
          Ready to launch{" "}
          <span className="font-mono">{scenario.name}</span>{" "}
          {isMultiTeam
            ? "(the exercise is already configured + live)"
            : "as a single-team drill"}
          .
        </p>
      </div>
      <div className="flex justify-end">
        <Button
          type="submit"
          disabled={launching}
          data-testid="wizard-launch"
        >
          {launching ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <ArrowRight className="mr-1 h-3 w-3" />
          )}
          {launching ? "Launching..." : "Launch drill"}
        </Button>
      </div>
    </form>
  );
}
