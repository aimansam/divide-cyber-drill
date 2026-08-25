# Section 18.4 — F10: Onboarding wizard

> **Status:** F10.1 + F10.2 + F10.3 + F10.4 shipped (commits
> `2ab897a` + `a8db813`). First-time operators get a 4-step guided
> flow instead of `tools/issue_token.py` + manual scenario upload.

## What F10 ships

A first-time user experience that takes a brand-new div:ide
deployment from "empty database" to "live drill running" in
under five minutes, all inside the browser:

```
   +-------------------+
   | Step 1:           |
   | Bootstrap admin   |  POST /api/v1/auth/setup
   |                   |  (single-shot; 409 if any user exists)
   +---------+---------+
             |
   +---------v---------+
   | Step 2:           |
   | Pick scenario     |  GET /api/v1/scenarios
   |                   |  (spec included so we know if it's
   |                   |  multi-team)
   +---------+---------+
             |
   +---------v---------+   +-------------------------+
   | Step 3 (optional):|   | Step 4 (single-team):   |
   | Form team         |   | Launch drill             |
   |                   |   |                         |
   | POST /exercises   |   | POST /api/v1/drills     |
   | POST /auth/users  |   |                         |
   | POST /start       |   |                         |
   +---------+---------+   +------------+------------+
             |                          |
             +------------+-------------+
                          |
                  onLaunched(runId)
                          |
                          v
                  DrillConsole
                  (Observe tab)
```

## What F10 is NOT

  * **No replacing the operator handoff.** `tools/issue_token.py`
    still works for SSH operators who prefer a CLI. The wizard is
    a parallel path; both mint HMAC tokens.
  * **No auto-fill of member passwords.** The wizard creates
    member users with the initial password `welcome-1234` so
    the operator can redistribute credentials out-of-band. A
    future plan can add per-user passwords + a "send invite"
    flow.
  * **No new scenario authoring.** Step 2 only picks from the
    existing catalog. New scenarios still go through the Admin
    tab's `ScenarioAuthoringCard` or `tools/sync_scenarios.py`.

## API contract

| Endpoint | Used by | Status codes |
|---|---|---|
| `POST /api/v1/auth/setup` | Step 1 | 201 (first admin), 409 (any user exists), 422 (bad body) |
| `GET /api/v1/scenarios` | Step 2 | 200 (now includes `spec`), 304 (cache hit) |
| `POST /api/v1/auth/users` | Step 3 | 201, 409 (dup sub, silently skipped), 422 (bad role), 401, 403 |
| `POST /api/v1/exercises` | Step 3 | 201, 409 (name conflict), 422 (bad scenario_id) |
| `POST /api/v1/exercises/{id}/start` | Step 3 | 200, 409 (already live/ended) |
| `POST /api/v1/drills` | Step 4 (single-team) | 201, 409 (in-progress), 422 (bad scenario) |

The wizard's `onLaunched(runId)` callback switches the portal to
the Observe tab + opens `DrillConsole` for the new run. The
operator lands on the same live view they'd see for any other
run.

## Why a wizard component (not 4 separate cards)

  * One operator task; splitting it into cards would force a
    parent to manage the step counter + form state.
  * Each step's data lives in the wizard's local state. The
    parent only sees two callbacks: `onLaunched` and
    `onSignInInstead`.
  * Step short-circuits (step 1 → 2 on 409, step 2 → 3 or 4
    based on the scenario's team count) live in the wizard.

## How step 1 routes on 409

When the wizard's first-admin POST returns 409 (admin already
exists), the wizard renders a callout with a "Sign in instead"
button. Clicking that flips a flag in `app.tsx` that swaps
`OnboardingWizard` for the existing `SignInCard`. The operator
sees no flicker; the layout container stays the same.

## Bundle budget

  * Pre-F10: 262.11 KB (17.89 KB headroom under the 280 KB
    ceiling).
  * Post-F10: 275.76 KB (4.24 KB headroom).

The wizard is JSX-heavy (4 step components + a step indicator
+ form fields + state). F12 (the next pillar) needs to land
without busting the budget; consider trimming the wizard
textarea or the step-indicator if F12 pushes us over.

## Tests

`services/api/tests/test_f10_setup.py` (11 tests) pins:

  * setup: 201 + LoginResponse on empty DB.
  * setup: 409 on second call (any user exists).
  * setup: 422 on password < 8 chars.
  * setup: 422 on empty sub.
  * users POST: 201 + UserPublic when admin creates user.
  * users POST: 409 on duplicate sub.
  * users POST: 422 on unknown role.
  * users POST: 401 anonymous.
  * users POST: 403 red.
  * users POST: 403 blue.
  * end-to-end: admin creates user -> user logs in -> token
    works.

Portal-side tests are not yet established; the wizard is
covered by `make verify-bundle` (still under 280 KB) +
typecheck + lint clean.

## Operator workflow

1. Operator runs `make up`. API is up. Portal is served at
   `localhost:8000/portal/app/`.
2. Operator opens the portal in a browser. **Sees the
   OnboardingWizard** (no token, no users yet).
3. Step 1: types admin sub + password, clicks "Create admin".
   Wizard stashes the token; operator is now authenticated as
   admin.
4. Step 2: picks `red-vs-blue-baseline` (a multi-team
   scenario shipped with the platform). Click "Next".
5. Step 3: leaves the team names at default `red` / `blue`,
   adds three usernames in the textarea, clicks "Create +
   launch exercise".
6. Wizard creates the exercise + members + starts it. The
   `onLaunched(exerciseId)` callback switches the portal to
   the Observe tab + opens DrillConsole on the new run.
7. Operator sees the live drill: topology, assets, audit feed,
   leaderboard (live), SOC stream (live). F11's "View debrief"
   button is ready for after the run finishes.

Total time: ~2 minutes. Pre-F10, the same outcome required:
SSH into the host, set `DIVIDE_BOOTSTRAP_ADMIN_*` env vars,
restart the API, log in, navigate to the Admin tab, upload a
scenario YAML, navigate to Operate, start the drill manually.

## Migration / rollout

F10 is **additive**:

  * `POST /api/v1/auth/setup` is a new endpoint; existing
    deployments that already have an admin see 409 (which the
    wizard handles gracefully).
  * `GET /api/v1/scenarios` now includes `spec` (additive).
    Existing callers that don't read `spec` are unaffected.
  * `OnboardingWizard` is mounted when no token is present.
    Existing users with a valid token see no change.

`make up && make verify` is the rollout gate.

## See also

  * [`docs/PLAN.md` §18.4](PLAN.md) — the F10 milestone in
    the plan doc.
  * [`docs/SECTION-9-INTEGRATION.md`](SECTION-9-INTEGRATION.md)
    — F9 DrillConsole consolidation — the destination view
    after the wizard launches a drill.
  * [`docs/SECTION-11-DEBRIEF.md`](SECTION-11-DEBRIEF.md) —
    F11 drill debrief — the post-drill artifact the operator
    can hand off.
  * [`docs/USERS.md`](USERS.md) — F3-prep credential auth
    model — the underlying auth that the wizard wraps.
