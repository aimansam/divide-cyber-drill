# Scenario Sync — YAML → DB

The repository is the source of truth for scenario definitions (see
[`SCENARIO-SPEC.md`](SCENARIO-SPEC.md)). To make scenarios queryable
by `scenario_id` (which the runner needs) we mirror the YAML files
into the `scenarios` table on every API startup.

## Lifecycle

```
examples/scenarios/foo.scenario.yaml
                │
                │  sync_files()  (startup, or `make sync-scenarios`)
                ▼
        ┌──────────────┐
        │  scenarios   │  ← CREATE / UPDATE in place by `metadata.name`
        │  (DB)        │
        └──────────────┘
                │
                │  runner.start_run(scenario_id)
                ▼
        ┌──────────────┐
        │  runs        │
        │  assets      │
        │  audit_log   │
        └──────────────┘
```

## What gets synced

For each file matching `*.scenario.yaml` / `*.scenario.yml` under the
configured `DIVIDE_SCENARIOS_DIR` (default `/workdir/examples/scenarios`)
plus any `DIVIDE_EXTRA_SCENARIOS_DIRS`:

1. **Validate** against `schemas/scenario.schema.json`. Invalid files
   are skipped (logged) but never crash the API.
2. **Upsert** into `scenarios`, keyed by `metadata.name`. If the YAML
   didn't change, no row update. If a field changed, the row is
   updated in place (including `version` if bumped).
3. **Archive** any active scenario whose `source_path` is no longer
   on disk: `archived_at = NOW()`. Runs that reference an archived
   scenario are preserved (FK `ON DELETE RESTRICT`).

Disabling the auto-archive: `DIVIDE_SYNC_ON_STARTUP=false` skips the
whole sync at boot. `make sync-scenarios --no-archive` does the same
for a single CLI invocation.

## How to add a new scenario

1. Drop `examples/scenarios/{name}.scenario.yaml` matching the schema.
2. Validate: `make validate-scenarios`
3. Commit. On next deploy, the API syncs it on startup.
4. List: `curl http://localhost:8000/api/v1/scenarios`

You can also POST a YAML body to `POST /api/v1/scenarios` without
restarting the API; the body is validated and upserted on the spot.

## How to retire a scenario

Move the YAML out of the configured scenarios dir, or set the
`archived_at` flag manually. The next sync will archive any other
active scenarios that have lost their backing YAML. Runs that
already reference the archived scenario remain queryable; new runs
against it return **410 Gone**.

To bring it back, restore the YAML at the same `source_path` (the
next sync un-archives automatically) or `POST /api/v1/scenarios/{name}/restore`.

## Manual sync

```bash
# Local dev (SQLite):
DIVIDE_DB_URL=sqlite+aiosqlite:///./divide.db \
  make sync-scenarios

# Against the running stack (auto-runs on container start):
make logs    # tail the api container; look for `divide_api.scenario_sync`
```

The CLI also supports a JSON output for piping into other tools:

```bash
python tools/sync_scenarios.py --json | jq '.created[].name'
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `DIVIDE_SCENARIOS_DIR` | `/workdir/examples/scenarios` | Where to look for YAML |
| `DIVIDE_EXTRA_SCENARIOS_DIRS` | (none) | Additional paths, semicolon-separated in the conftest, comma-separated env |
| `DIVIDE_SYNC_ON_STARTUP` | `true` | Auto-sync on API boot |
| `DIVIDE_SCENARIO_SCHEMA` | (auto-discovered) | Override the JSON Schema path |

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `/scenarios` returns empty | Sync skipped (env var set), or scenarios dir empty/missing | Check logs for `scenario_sync.failed` |
| `skipped` items in `SyncReport` | YAML fails JSON Schema validation | Fix the YAML; `validate-scenario` is in CI |
| Postgres enum error on insert | Stale DB enum definitions (pre-`values_callable`) | Re-run `alembic upgrade head` |
