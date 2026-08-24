# F7 Runbook — Range Templates

> **Status:** F7 shipped (`fa20fb3` + `7c4f03a` + `aba76b2`). (✅ shipped; see [PLAN.md §15.6](PLAN.md) for the full §15 closure summary.)
> Templates let operators snapshot a Run's end-state and replay
> it deterministically.  Drills become repeatable artifacts
> instead of one-shot experiments.

> **Audience:** admin/lead operators running repeatable drills;
> observers auditing past runs.

## TL;DR

A template is an **immutable JSONB snapshot** of a Run's
scenario, assets, flags, networks, and scoring rules.  Once
captured it never changes; if you want a different state,
snapshot a different Run.

```bash
# 1. Snapshot a finished drill into a template.
# Requires admin role and a Run in SUCCEEDED / FAILED / ENDED.
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "router-baseline-v1",
    "title": "Router Baseline (v1)",
    "description": "Working state from 2026-08-25",
    "from_run_id": 42
  }' \
  http://localhost:8000/api/v1/templates

# 2. Replay the template into a fresh Run.
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": 7, "template_id": 1}' \
  http://localhost:8000/api/v1/drills

# 3. While a drill is running, "bookmark" its current state.
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "mid-drill-1", "title": "Bookmark at t=15"}' \
  http://localhost:8000/api/v1/drills/42/save-as-template

# 4. Reset a Run back to its template's snapshot.
# Requires the Run to be bound to a template via save-as-template
# or a clone.
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/drills/42/reset

# 5. List / delete templates.
curl -H "X-Divide-Token: $OBSERVER_TOKEN" \
  http://localhost:8000/api/v1/templates

curl -X DELETE -H "X-Divide-Token: $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/templates/1
```

## Why templates?

Drill reproducibility is the single biggest complaint operators
have about every range platform that doesn't have them.  With
templates:

  * **Demo recordings stay faithful.**  The Q3 Tabletop that
    ran in 2026-Q3 can be replayed verbatim for the 2027-Q3
    training session — same asset placement, same flags, same
    networks.  No more "what template did we use last time?".
  * **Operator onboarding.**  New operators run *real*
    templates instead of staring at YAML for an hour.
  * **Drift detection.**  When the live scenario YAML changes,
    `template.snapshot.scenario_version` makes drift visible:
    the portal shows the version next to each template row.

## Lifecycle

```
                  +------------+
   POST /templates (from SUCCEEDED Run)
                  |
                  v
            +-----------+
            | Template  |  (immutable; never updated)
            +-----------+
                  ^
                  |  POST /drills/{id}/save-as-template
                  |  (captures a live Run's state)
                  |
                  +--- Run (live) ---> save-as-template binds
                                          run.template_id

   POST /drills (with template_id)        POST /drills/{id}/reset
       spawns a Run from the template       reverts a Run's assets
                                            to its template snapshot
```

Templates are **never updated in place**.  If a template needs
to change, the operator creates a new one.  This means the
template's `name` is forever stable; a downstream run reference
never rots.

## Snapshot schema

```json
{
  "scenario_id": 7,
  "scenario_name": "red-vs-blue-baseline",
  "scenario_version": 1,
  "assets": [
    {"role": "router", "kind": "vm",
     "template": "tpl-router", "networks": ["mgmt", "victim"]}
  ],
  "flags": [
    {"id": "router-default-creds",
     "side": "red", "value": "FLAG{admin:admin}",
     "planted_on_role": "router",
     "base_points": 100}
  ],
  "networks": [
    {"name": "mgmt", "cidr": "10.0.0.0/24"},
    {"name": "victim", "cidr": "10.1.0.0/24"}
  ],
  "scoring": {...},
  "win_conditions": {...},
  "run_status_at_snapshot": "succeeded"
}
```

The snapshot is intentionally **self-contained** so a template
can be replayed against a frozen scenario even if the scenario
YAML was edited afterward.  Future plans (F7.5) may snapshot
the *full* scenario YAML too — today the snapshot lives at the
level of "what the runner needs to start a fresh run".

## Reset semantics

`POST /drills/{id}/reset` is the operator's "undo" button:

  1. Wipes the run's `Asset` rows (cascade deletes their child
     `FlagSubmission` / `TelemetryEvent` rows — operator loses
     the in-flight scoring history).
  2. Re-stages `Asset` rows from the template's snapshot.
  3. Sets `run.status = PENDING`, clears `started_at`,
     `ended_at`, `score_red`, `score_blue`.
  4. The next runner tick picks up the run and starts fresh.

**Reset requires a bound template.**  A Run that was spawned
from raw scenario YAML (no template) cannot be reset because
the runner has no canonical "good state" to revert to.  Use
`/drills/{id}/save-as-template` first if you want a resettable
Run.

**Reset is destructive.**  Anything that happened on the live
range (captured flags, telemetry, in-flight scoring) is lost.
Use sparingly.  Future plans: snapshot the pre-reset state so
reset is reversible.

## RBAC matrix

| Action | admin | lead | red/blue | observer |
|---|---|---|---|---|
| List / view | ✅ | ✅ | ✅ | ✅ |
| Clone (POST /drills with template_id) | ✅ | ✅ | ✅ | ❌ |
| Save-as-template | ✅ | ❌ | ❌ | ❌ |
| Reset | ✅ | ✅ | ❌ | ❌ |
| Create from SUCCEEDED run | ✅ | ❌ | ❌ | ❌ |
| Delete | ✅ | ❌ | ❌ | ❌ |

Templates are **shared across teams** (no per-team filtering).
Future "private" tier deferred.

## What's NOT in F7 (and where it lives)

- **Restore from backup**: not implemented. Templates are
  operational snapshots, not cold-storage. Use Postgres
  backups for that.
- **Template diff UI**: future. F7 just gives the JSON; the
  portal shows `scenario_version` next to each row.
- **Template versioning** (template_v1, template_v2 of the
  same scenario): future. Today the operator creates a new
  template with a new name; the old one stays.
- **Auto-snapshot on every RUN -> SUCCEEDED**: deferred to
  F7.5. Today the operator / runner must explicitly trigger
  save-as-template.

## See also

- [`docs/DEMO.md`](DEMO.md) — operator walkthrough uses
  templates for the "replay yesterday's drill" demo
- [`docs/F5-SCORING.md`](F5-SCORING.md) — flag-side context
  (templates snapshot the F5 scoring rules too)
- [`docs/F6-MULTITEAM.md`](F6-MULTITEAM.md) — multi-team runs
  are templatable (one template, many team-scoped runs)
- [`schemas/scenario.schema.json`](../schemas/scenario.schema.json)
  — scenario-side schema; templates capture `spec.assets` /
  `spec.flags` / `spec.networks` from this
