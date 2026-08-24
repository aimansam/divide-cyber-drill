# F5 Runbook — Flags, Scoring, and Captures

> **Status:** F5 shipped (`98e4e7c` + `85ecf29`). Scenarios can (✅ shipped; see [PLAN.md §15.6](PLAN.md) for the full §15 closure summary.)
> declare `spec.flags[]`; teams capture flags via
> `POST /api/v1/drills/{id}/submit-flag`; the API scores them
> with linear time-decay.
>
> **Audience:** red/blue operators running live drills who
> need to plant + capture flags; admins who need to understand
> the scoring formula.

## TL;DR

For the cyber-range demo (the scenario is red-vs-blue-baseline), the scenario declares 3 flags:

| Flag | Planted on | Side | Window | Base |
|---|---|---|---|---|
| `red-flag-file-server`     | `file_server`    | red | 30 min | 100 |
| `red-flag-log-aggregator`  | `log_aggregator` | red | 30 min | 100 |
| `red-flag-router`          | `router_fw`      | red | 30 min | 100 |

A red team captures a flag by SSH'ing into the asset and reading
its filesystem (typically `/root/flag.txt` for `file_server`), then
submitting the value via:

```bash
curl -X POST -H "X-Divide-Token: $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"flag_id":"red-flag-file-server","value":"FLAG{rooted_file_server}"}' \
     http://localhost:8000/api/v1/drills/42/submit-flag
# -> {"flag_id": "red-flag-file-server", "team": "blue", "points": 95, ...}
```

The server returns the **points awarded** (out of `base_points`)
and the **breakdown** for the after-action report.

## Scoring formula

```
points = floor( base_points * max(0, min(1, 1 - elapsed / window)) )
```

  * At `t=0` (flag captured immediately after `run.started_at`)
    the team gets the full `base_points`.
  * At `t=window` the award is 0.
  * Past the window: still 0 (no negative-award penalty).
  * The score is **floored**, never rounded up, so the awarded
    value never exceeds the base. See
    `app/services/scoring.py:score()`.

This is intentionally simple compared to industry CTF scoring
(k-CTF and similar use 10-min exponential windows); F5 doesn't
need anything fancy to demo the leaderboard. The score formula
is a single function; the unit tests pin it row by row.

## What the runner does

F5's runner integration (`app/runners/runner.py`) adds one
sub-step before the run flips to SUCCEEDED:

  * For each entry in `spec.flags[]`, emit a `flag.planted`
    audit row. The row carries: `flag_id`, `side`, the planted
    role, base points, decay window, and a `value_present` flag
    (the actual value is **never** in the audit log).
  * If `planted_on_role` matches an asset row that's already
    been cloned, link the audit row to that asset_id. Otherwise
    the audit row has `asset_id = None` (the operator sees this
    and investigates).
  * The actual filesystem write is **not** part of F5 — the
    runner records *intent*. Planting happens via cloud-init
    `user_data` baked into the asset template, or a follow-up
    script that SSHs into each asset and writes the file (see §3
    below).

So F5 ships:

  * The schema field (`spec.flags[]`).
  * The DB row (`flag_submissions`).
  * The submission endpoint (`POST /submit-flag`).
  * The runner integration (audit rows).

What's left (explicitly deferred):

  * The actual filesystem write — left to user_data or a
    follow-up plan.
  * A leaderboard UI — comes with F6 (multi-team).
  * Flag rotation — when a flag is "leaked" outside the drill,
    the operator should be able to regenerate it. F5 stores
    flags per-scenario, not per-run, so this needs the runner
    to refresh the audit row before each drill.

## Authoring a flag

In your scenario YAML:

```yaml
spec:
  flags:
    - id: red-flag-DC
      side: red              # red hunts
      value: "FLAG{rooted_domain_controller}"
      planted_on_role: dc_server
      decay_window_seconds: 1800    # 30 minutes
      base_points: 250
```

That's it. The runner picks up the flag and the operator can
submit it via the endpoint. The DB enforces the unique
constraint `(run_id, flag_id, team)` so no team can capture
the same flag twice for the same run (and the leaderboard
can't be double-counted).

## How teams capture a flag in practice

The realistic flow is:

1. Red attacker SSHes to `file_server` via the router's NAT.
2. Inside the shell, reads `/root/flag.txt` →
   `FLAG{rooted_file_server}`.
3. Curl submits it (the team has an X-Divide-Token from the
   sign-in screen).

The blue team's job is to detect step 1 via the `log_aggregator`
syslog feed and shut the attacker down before step 3 happens.
That's the F4 demo narrative.

## RBAC rules

| Role | Submit flag | View own team's score | View all scores |
|---|---|---|---|
| admin | yes | yes | yes |
| lead | yes | yes | yes |
| red | yes (own run only) | yes | no |
| blue | yes (own run only) | yes | no |
| observer | no | yes | yes |

The current scope pins: "you can submit a flag for a run you
own OR if you're admin/lead." A future plan (F6 multi-team)
might split this per-team (red-side flags are mined by the blue
team; the leaderboard needs to surface "team A captured X,
team B didn't").

## Common errors

| Error | Why |
|---|---|
| `HTTP 422 "flag value did not match"` | The submitted value doesn't match `spec.flags[].value`. Tip: flags are case-sensitive; watch for trailing whitespace. |
| `HTTP 404 "flag {id} not in scenario"` | The flag id isn't in `spec.flags[]`. Confirm via `GET /api/v1/scenarios` (returns the spec). |
| `HTTP 404 "run id=N not found"` | The run doesn't exist (or you can't see it). |
| `HTTP 409 "team 'blue' already captured flag 'f1'"` | You already captured this flag for this run. The unique constraint fired. |
| `HTTP 409 "run is succeeded; flags can only be captured..."` | The drill is over. Flags can only be captured while the run is RUNNING or PENDING. |
| `HTTP 422 "flag is self-side; F5 only scores red/blue side flags"` | A `self`-side flag was submitted. F5 doesn't score those yet — we have them in the schema for F8 (SOC view) to use as proof-of-life. |

## What's NOT in F5 (and where it lives)

- **Leaderboard UI** — F6 multi-team.
- **Planting via SSH / file write** — operator-managed for now
  (cloud-init `user_data`); the runner ships the audit row.
- **Flag rotation** — post-F5. A leaked flag stays leaked.
- **Multi-team flag pulling** — F6. Today each team captures
  against the same global flag list.
- **Per-team flag subsets** — F6.
- **Self-side flag scoring** — F8 (used for SOC view).

## See also

- [`docs/DEMO.md`](DEMO.md) — the operator's demo walkthrough
- [`docs/PORTAL-UI.md`](PORTAL-UI.md) — F4-UI portal surfaces
- [`docs/F4-NOVNC.md`](F4-NOVNC.md) — F4 console plumbing
- [`docs/PLAN.md`](PLAN.md) §15 — F5 unblocks F6 (leaderboard)
  and F8 (SOC view uses self-side flags for proof-of-life).
- [`schemas/scenario.schema.json`](../schemas/scenario.schema.json)
  — `spec.flags[]` shape, locked by these tests.
