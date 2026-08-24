# Section 9 — DrillConsole Consolidation (F9.1)

> **Status:** F9.1 + F9.2 + F9.3 shipped. The Observe tab is the
> single live-drill screen: status / topology / assets / console /
> audit feed / leaderboard (5s polling) / live SOC stream — no more
> tab flipping during a multi-team drill. ``make verify-bundle``
> enforces the 280 KB ceiling; ``make verify`` runs it as the 5th
> step. F9 milestone is CLOSED.

## What F9.1 changes

Pre-F9.1, an operator running a multi-team exercise had to flip
between two tabs to watch the live drill:

  * **Observe** — `DrillConsole` (status, topology, assets,
    VNC console, audit feed).
  * **Admin** — `LeaderboardCard` (per-team score).

The blue-team SOC view (`SocViewCard`) was wired standalone, not
embedded in either tab — so the SOC analyst would either pin it in
a separate window or copy/paste the run ID.

F9.1 consolidates everything into the `DrillConsole` component:

```
Run.exercise_id === null         Run.exercise_id !== null
  (legacy single-team)             (F6 multi-team exercise)
  +----------------------+         +----------------------+
  | status header         |         | status header         |
  | topology              |         | topology              |
  | assets                |         | assets                |
  | picked asset -> console|       | picked asset -> console|
  | audit feed            |         | audit feed            |
  |                       |         |                       |
  |                       |         | --- F9 NEW ---        |
  |                       |         | leaderboard           |
  |                       |         | live SOC stream       |
  +----------------------+         +----------------------+
```

For single-team Runs the new sections stay hidden — the Admin tab
remains the right place for the leaderboard in that flow.

## What F9.1 is NOT

  * **No new endpoint.** `GET /api/v1/drills/{id}` was the only
    API change: it now returns `exercise_id` (a single additive
    field). All UI panels use existing endpoints:
      * `GET /api/v1/exercises/{id}/leaderboard` — F6
      * `GET /api/v1/runs/{id}/events/stream` — F8 SSE
      * `GET /api/v1/runs/{id}/events/recent` — F8 cold-replay
  * **No new portal component.** `LeaderboardCard` and
    `SocViewCard` already existed; F9.1 just imports + renders
    them conditionally inside `DrillConsole`.
  * **No backend work beyond the additive `exercise_id` field.**
    No migrations; no model changes; no router changes beyond
    the one new key in the response dict.

## Operator-facing behavior

For a single-team Run (most common; `exercise_id === null`):

  * Observe tab renders exactly as before F9.1.
  * Admin tab still shows `LeaderboardCard` if the operator wants
    a wide-screen view, but it's no longer required to monitor the
    drill.

For a multi-team Run (`exercise_id !== null`):

  * Observe tab adds two new sections below the audit feed:
    **Leaderboard** (live, polls every 5 s) and **Live SOC
    stream** (SSE-driven, with severity filter + pause/resume).
  * The two sections keep polling / streaming as long as the run
    is picked. Closing the tab and re-opening it reconnects the
    SSE stream and replays the last 50 events.

## Implementation details

### Backend (1 file, 4 lines added)

`services/api/app/routers/drills.py::get_drill`:

```python
return {
    "run_id": run.id,
    "scenario_id": run.scenario_id,
    # F9.1: expose exercise_id so the portal DrillConsole can
    # decide whether to render the multi-team panels (leaderboard
    # + live SOC stream) inline. Legacy single-team Runs have
    # exercise_id === null.
    "exercise_id": run.exercise_id,
    "status": run.status.value,
    ...
}
```

### Frontend (2 files)

`services/portal/app/src/components/portal/run-lifecycle-card.tsx` —
add `exercise_id?: number | null` to the `RunDetail` interface.

`services/portal/app/src/components/portal/drill-console.tsx` —
import `LeaderboardCard` + `SocViewCard`; render them
conditionally after the audit feed when `run.exercise_id != null`.
The conditional uses `!= null` (not `!== null`) so undefined is
treated the same as null and the section stays hidden until the
API responds.

## Tests

5 new tests in `services/api/tests/test_f9_drill_console.py`:

  1. `test_get_drill_returns_null_exercise_id_for_single_team` —
     legacy Runs expose `exercise_id === null`.
  2. `test_get_drill_returns_exercise_id_for_multi_team` — F6
     Exercise Runs expose the bound `exercise_id`.
  3. `test_get_drill_exercise_id_is_idempotent` — repeated GETs
     return the same value (no caching surprises).
  4. `test_get_drill_unknown_run_returns_404` — regression: the
     new field didn't break the 404 path.
  5. `test_get_drill_anonymous_returns_401` — regression: the
     auth gate still fires.

Total tests after F9.1: **864** (was 859 + 5 new).

## Bundle budget

| Stage | Bundle | Headroom (under 280 KB) |
|---|---|---|
| Pre-F9.1 (post-§15 closure) | 246.45 KB | 33.55 KB |
| F9.1 | 260.55 KB | 19.45 KB |
| F9.2 | 260.68 KB | 19.32 KB |
| F9.3 | 260.68 KB | 19.32 KB (gzip: 77.45 KB) |

F9.1 added ~14 KB (the LeaderboardCard + SocViewCard imports
inside DrillConsole's already-loaded module graph). F9.2 added
~130 bytes (the polling interval logic). F9.3 is bundle-neutral
(Makefile + pytest only); the bytes are unchanged.

Total tests added across F9: **10** (5 in `test_f9_drill_console.py`
+ 5 in `test_f9_bundle_budget.py`).

## F9.3 — bundle-budget gate

The 280 KB ceiling was previously enforced only by reviewer
discipline (the §15 closure summary noted the bundle was "still
under 280 KB"). F9.3 makes it a hard gate:

  * **`Makefile::verify-bundle`** — builds the portal and fails
    if the JS bundle exceeds 280 KB. Uses python3 for size +
    comparison so it works in minimal containers (no `bc`/`stat`
    required).
  * **`make verify`** — now a 5-step gate. The bundle-budget
    step runs last, after lint + test + preflight + smoke.
  * **`tests/test_f9_bundle_budget.py`** — 5 tests pinning the
    threshold, the inclusive boundary, the failure path, and
    the real-portal-bundle size. The Makefile target is the
    canonical gate; this test is the in-process regression net.

Output on a clean tree:

```
bundle: 254.57 KB (limit 280.00 KB)
OK: bundle within budget
```

The threshold (280 KB) and the comparison logic are exercised
both in `make verify-bundle` (canonical) and in `make test`
(regression net).

## What's deferred to F9.x (post-F9.3)

  * Keyboard shortcut to focus the Leaderboard / SOC sections
    in DrillConsole.
  * Sidebar nav anchor for the F9 panels.

These are UX polish on top of the F9 milestone; the live-drill
single-screen property is fully in place after F9.1 + F9.2 +
F9.3.

## Migration / rollout

F9.1 is **backwards-compatible**:

  * The new `exercise_id` field is additive; old clients ignore
    it.
  * The conditional render in DrillConsole is purely additive;
    the existing layout for single-team Runs is unchanged.
  * No DB migration; no env var changes; no docker-compose
    changes.

Rollout is a normal `make up && make verify` cycle.

## See also

  * [`docs/PLAN.md` §18.1](PLAN.md) — the F9 milestone in the
    plan doc.
  * [`docs/F6-MULTITEAM.md`](F6-MULTITEAM.md) — F6 (multi-team
    exercises) — the source of `run.exercise_id`.
  * [`docs/F8-SOC.md`](F8-SOC.md) — F8 (SOC view + SSE) — the
    source of the live event stream consumed by `SocViewCard`.
