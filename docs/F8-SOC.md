# F8 Runbook — SOC View + Live Telemetry

> **Status:** F8 shipped (`d88dbe6` + `7a987f9` + `aba76b2`).
> The cyber range now streams live events to a SOC dashboard.
> The runner, flag-capture, asset-spawn, and human-injected
> events all flow through a single EventBus + DB record.

> **Audience:** blue team operators watching a live drill;
> SOC analysts doing post-mortem on a finished run.

## TL;DR

```bash
# 1. Inject a custom event (admin/lead). Useful for
# surfacing a "kill-chain signal" the runner didn't catch.
curl -X POST -H "X-Divide-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "kill-chain.signal",
    "severity": "high",
    "payload": {"message": "ssh bruteforce detected"}
  }' \
  http://localhost:8000/api/v1/runs/42/events

# 2. List events for a run (history).
curl -H "X-Divide-Token: $OBSERVER_TOKEN" \
  "http://localhost:8000/api/v1/runs/42/events?severity=high&limit=50"

# 3. Live tail via SSE.
curl -N -H "X-Divide-Token: $OBSERVER_TOKEN" \
  http://localhost:8000/api/v1/runs/42/events/stream
# Output:
#   event: hello
#   data: {"run_id": 42, "ts": "..."}
#
#   event: history
#   data: {"id": 1, "kind": "run.started", ...}
#   ...
#   event: live
#   data: {"id": 99, "kind": "flag.captured", "severity": "medium", ...}
#
#   : ping    <-- heartbeat every 10s
```

## Event types

| Kind | Source | Severity | When |
|---|---|---|---|
| `run.started` | runner | info | Drill begins. |
| `run.completed` | runner | info | Drill ends (SUCCEEDED). |
| `asset.running` | runner | info | An asset's VM is up. |
| `flag.captured` | submit-flag | medium | A flag is captured. |
| `kill-chain.signal` | manual | configurable | Operator-injected signal. |

More kinds will be added as F8.5+ expands coverage (auth
attempts, lateral movement, etc.).

## Severity buckets

Four buckets: `info` / `low` / `medium` / `high`. Intentionally
coarse -- SOC analysts filter on these in the SOC view; finer
levels (e.g. NIST 800-61's 6-level scale) would be visual noise.
F8.5 may map our 4 buckets to a finer scale in the back end
while keeping the wire format the same.

## Architecture

```
                       +-------------------+
   POST /runs/{id}/    |                   |   bus.publish(event)
   events (manual) --> |  event_recorder   | ----------------+
                       |  (DB + Bus)       |                  v
                       +-------------------+         +--------------+
                                                     | EventBus     |
   runner.start_run --> event_recorder  ------------> | (in-process) |
   submit-flag --------> event_recorder  ------------> | ring buffer  |
   ...                                           |  subscribers |
                                                +--------------+
                                                       |
                                                       v
                                                 SSE: /events/stream
                                                       |
                                                       v
                                                 Portal SOC view
```

**EventBus:** in-process pub/sub. F8 single-worker;
multi-worker deployments need Redis pub/sub (F8.5).
The bus caps at 1024 events; older events drop on overflow.
A reconnecting client fetches `/events/recent` for replay
on cold-connect.

**Persistence:** every event also lands in the
`telemetry_events` table. SSE handlers don't go through the DB
(the bus is the live tail); the DB is the cold record. Soft
deletion via future retention job.

## SOC view UX

The portal `SocViewCard` (Operator console tab) shows:

  * **Live indicator** (green = connected via SSE; red = lost).
  * **Severity filter** (All / High / Medium / Low / Info).
  * **Pause / Resume** button. When paused, new events queue
    in a frozen buffer; on resume they flush in.
  * **Event stream** with timestamp + kind + source +
    truncated payload.

The card pulls 50 events on mount (`/events/recent?n=50`) then
connects to SSE for the live tail. Heartbeats every 10s prevent
proxy-disconnect.

## RBAC matrix

| Action | admin | lead | red/blue | observer |
|---|---|---|---|---|
| Inject event | ✅ | ✅ | ❌ | ❌ |
| Read history | ✅ | ✅ | ✅ | ✅ |
| Live stream (SSE) | ✅ | ✅ | ✅ | ✅ |

The SOC view is shared across all roles so observers can
watch live drills. Red and blue see only their own runs'
streams (via the run selector in the operator console).

## What's NOT in F8 (and where it lives)

- **Multi-worker pub/sub** (Redis): F8.5. Today the bus is
  in-process; if you run uvicorn with `--workers 2`, an event
  published on worker A is not seen by SSE subscribers on
  worker B. The DB row IS persisted across workers; clients
  reconnecting via `/events/recent` will still see all events.
- **Per-event retention policies**: F8.5. Today rows are
  append-only; a future cleanup job prunes after 24h.
- **Replay UI** (scrub through past events with playhead):
  F8.5+ with built on the SOC view's filter + paginated
  history.
- **Auto-correlation across events** (e.g. "this SSH bruteforce
  event matches the asset.running event 30s earlier"):
  F9+. The SOC view shows raw events today.
- **Wazuh / ELK ingest**: deferred. The runner already
  emits to user-configured telemetry sinks (L2 2.11);
  that's the existing path.

## See also

- [`docs/DEMO.md`](DEMO.md) — the SOC view is on stage during
  the live demo
- [`docs/F5-SCORING.md`](F5-SCORING.md) — flag-capture events
  surface scoring activity (medium severity)
- [`docs/F6-MULTITEAM.md`](F6-MULTITEAM.md) — multi-team
  exercises: events carry `exercise_id` in their payload
- [`docs/F7-TEMPLATES.md`](F7-TEMPLATES.md) — templates don't
  generate events; they're snapshots of past runs
