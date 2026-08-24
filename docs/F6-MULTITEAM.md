# F6 Runbook — Multi-Team Exercises

> **Status:** F6 shipped (`5386096` + `d7e69f9` + `aba76b2`).
> Scenarios can declare multiple teams; an Exercise binds them;
> each team has its own Run; flag captures aggregate into a
> team score that the leaderboard reads.

> **Audience:** admin/lead operators running a competitive
> red-vs-blue drill; observers reading the leaderboard.

## TL;DR

For the cyber-range demo scenario (`red-vs-blue-baseline`),
the F6 wiring lets you set up:

  1. An Exercise (a "tabletop" or "competition" instance of the
     scenario)
  2. Two Teams inside the Exercise: `red` + `blue`
  3. Two Runs, one per team, both cloning from the same scenario YAML
  4. Members on each team who can submit flags
  5. A leaderboard that surfaces the cumulative red/blue scores

```bash
# 1. Create the exercise
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "tabletop-2026-09-12",
    "title": "Q3 Tabletop",
    "scenario_id": 7,
    "teams": [
      {"name": "red",  "color": "#dc2626"},
      {"name": "blue", "color": "#2563eb"}
    ]
  }' \
  http://localhost:8000/api/v1/exercises

# 2. Move the exercise to LIVE
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/exercises/1/start

# 3. Add members
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sub": "alice", "team_id": 1}' \
  http://localhost:8000/api/v1/exercises/1/members

# 4. Start a run scoped to the red team
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": 7, "exercise_id": 1, "team": "red"}' \
  http://localhost:8000/api/v1/drills

# 5. Capture a flag from blue's perspective (red-side flag hunted by blue)
curl -X POST -H "X-Divide-Token: $BLUE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"flag_id": "red-flag-router", "value": "FLAG{default_creds_router}"}' \
  http://localhost:8000/api/v1/drills/42/submit-flag

# 6. Read the leaderboard
curl -H "X-Divide-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/exercises/1/leaderboard
# Returns: {exercise_id, teams: [{rank, name, color, score}, ...]}
```

## Lifecycle

```
           +-------+    start   +------+   stop    +-------+
           | idle  | ---------> | live | --------> | ended |
           +-------+            +------+           +-------+
              |   |                |  |                |
              |   +-- start -------/  |                |
              |                       |                |
              |                       +-- start (reopen)
              |                                        |
              +---- any state --- archive ---------> +----------+
                                                       | archived |
                                                       +----------+
```

`Exercise.transition_to()` enforces this FSM. Skipping `live` is
rejected (`IDLE -> ENDED` returns 409), so a misclick on `/stop`
during IDLE doesn't end an exercise that never started.

`archived` is reachable from any state — that's the post-mortem
snapshot. Once archived, the Exercise is read-only; runs and
teams remain queryable but no new runs can start.

## Architecture

  * Each Run now has `run.exercise_id` (nullable) and `run.team`
    (nullable). Legacy single-team runs have both `null`; the F5
    flag submission endpoint computes red/blue scores per Run
    regardless of the Exercise it lives in.
  * The leaderboard is computed at read-time from `Team.score`
    (an integer). The F5 submit-flag endpoint atomically
    increments `team.score += points` when the run is in an
    Exercise, so the leaderboard reads a denormalized int that's
    always fresh.
  * Members register with `TeamMembership(sub, exercise_id,
    team_id, role)`. The unique constraint `(sub, exercise_id)`
    means one user can be on at most one team per Exercise — but
    they can be on a different team in a different exercise.

## RBAC matrix

| Role | Create / mutate | Read exercise | Read leaderboard | Submit flag |
|---|---|---|---|---|
| admin | ✅ | any | any | any |
| lead  | ✅ start/stop/archive | any | any | any |
| red   | ❌ | own exercises (member) | own exercises | own run |
| blue  | ❌ | own exercises (member) | own exercises | own run |
| observer | ❌ | any | any | ❌ |
| unauthenticated | ❌ | ❌ | ❌ | ❌ |

The operator console (`OperatorConsoleCard`) shows the active
exercises the operator is a member of.

## What's NOT in F6 (and where it lives)

- **Per-team scenario surfaces** (e.g. red sees only their run,
  not the blue one) — F6.5 follow-up. Current behaviour: red sees
  all runs in their exercise (filtered by team visibility). Use
  the F8 SOC view for live events.
- **Multi-team score breakdown** (per-flag contribution chart on
  the leaderboard) — future. F8 SOC view handles live events but
  not historical replay.
- **Flag rotation across exercises** — out of scope.
- **Exercise re-use across runs** — done via `Exercise` model.
  The runner spawns a fresh Run per team.

## See also

- [`docs/DEMO.md`](DEMO.md) — the operator walkthrough
- [`docs/F5-SCORING.md`](F5-SCORING.md) — scoring formula + flag
  capture flow (F5 feeds the leaderboard via Team.score)
- [`docs/PORTAL-UI.md`](PORTAL-UI.md) — the LeaderboardCard lives
  on the Admin tab (`compose-admin-tabs`)
- [`docs/PLAN.md`](PLAN.md) §15 — F6 closes G4 + L3 3.13 partial
- [`schemas/scenario.schema.json`](../schemas/scenario.schema.json)
  — flag schema (still pinned by F5)
