# Section 18.2 — R1: Multi-worker SSE via Redis pub/sub

> **Status:** R1.1 shipped (commit `19d5cce`). The platform now
> fans out SSE events across uvicorn workers. Set
> `DIVIDE_EVENT_BUS=redis` to enable.

## The problem R1 solves

Pre-R1, the EventBus was an in-process pub/sub. With a single
uvicorn worker, this is fine: every SSE handler runs in the
same process as the publisher. With multiple workers (the
production-grade deployment), this breaks:

  * Worker A clones a VM, emits `asset.running` via the bus.
  * The bus fans out to subscribers **on worker A only**.
  * An SSE handler on worker B (the operator happens to have
    landed there) never sees the event.

This was acceptable for F8 (single-worker LAN deployment) but
unacceptable for any production-grade deployment.

## What R1 ships

A second implementation of the `EventBus` Protocol,
`RedisEventBus`, backed by:

  * **Channel:** `divide:events:global` — every published event
    hits this Redis pub/sub channel. Every worker subscribed to
    `RedisEventBus` receives a copy.
  * **Ring buffer:** Redis LIST `divide:events:buffer` — capped
    at 1024 entries via `LTRIM` after every `LPUSH`. Replaces
    the in-process `deque(maxlen=1024)`.

`publish()` LPUSHes + LTRIMs the buffer and PUBLISHes the
event. `subscribe()` first replays the buffer (LRANGE), then
joins the live feed. `recent(n)` reads the buffer with the
same oldest-last ordering as the in-process bus.

The bus is bridged into the Python sync world via a daemon
thread that runs an asyncio loop + an `redis.asyncio`
pubsub subscription. Publishers + subscribers stay sync — the
existing F8 callers (`app.routers.events`,
`app.services.event_recorder`) work unchanged.

## API surface (unchanged from F8)

```python
bus = build_event_bus()  # auto-selected via env var

bus.publish({"id": 1, "kind": "run.started", "run_id": 7})
q, unsub = bus.subscribe()  # returns (queue, unsubscribe)
ev = q.get(timeout=30)      # blocks until an event arrives
recent = bus.recent(50)     # last 50 events from the buffer
unsub()
```

Both `InProcessEventBus` and `RedisEventBus` implement the same
`EventBus` Protocol — pick the implementation with the env var
and the rest of the codebase doesn't change.

## Selecting the backend

`build_event_bus()` reads `DIVIDE_EVENT_BUS`:

| Value | Backend | When |
|---|---|---|
| `redis` | `RedisEventBus` | Multi-worker deployments |
| `memory` (default) | `InProcessEventBus` | Single-worker (LAN, dev) |
| unset | `InProcessEventBus` | Same as `memory` |
| anything else | `InProcessEventBus` (with warning) | Misconfig |

`docker-compose.yml` defaults to `memory` so single-worker
deployments work out of the box. Operators upgrading to
multi-worker set:

```yaml
environment:
  DIVIDE_EVENT_BUS: redis
  DIVIDE_REDIS_URL: redis://redis:6379/0
```

Or override at the shell:

```bash
DIVIDE_EVENT_BUS=redis docker compose up -d
```

## Deployment topology

```
   worker A (uvicorn)                worker B (uvicorn)
   +----------------+                +----------------+
   | EventBus:      |                | EventBus:      |
   | RedisEventBus  |                | RedisEventBus  |
   | (sync client)  |                | (sync client)  |
   +-------+--------+                +-------+--------+
           |                                  |
           | LPUSH/LTRIM/PUBLISH              |
           v                                  v
   +----------------------------------------------------+
   | Redis                                              |
   |   LIST divide:events:buffer   (1024-entry ring)    |
   |   CHAN divide:events:global   (pub/sub fan-out)    |
   +----------------------------------------------------+
                                ^
                                | SUBSCRIBE
                                |
              bridge thread in each worker:
              asyncio loop + redis.asyncio pubsub
              -> forwards into per-subscriber queue.Queue
```

## Failure modes + observability

  * **Redis unreachable on startup.** `build_event_bus()` does
    NOT probe Redis — it just instantiates `RedisEventBus`.
    The first `subscribe()` call attempts to start the bridge
    thread; if Redis is unreachable, the bridge raises and
    `subscribe()` surfaces the error to the SSE handler (500
    on the SSE GET). Logs show
    `redis_event_bus: bridge thread failed to start`.
  * **Redis dies mid-drill.** The bridge's `get_message()`
    loop will raise on the next iteration; the catch-all in
    `_bridge_async` swallows + logs; subsequent publishes to
    the bus will raise on `pipe.execute()`. The SSE handler
    is best-effort here — fix Redis, reconnect.
  * **Buffer grows unbounded.** Impossible — `LTRIM` caps at
    1024 after every `LPUSH`. With 1k events/sec the buffer
    stays at 1024 + a few in-flight entries.
  * **Bridge thread crash.** `_bridge_started.wait(timeout=5)`
    catches the first failure; subsequent `subscribe()` calls
    attempt to restart the bridge (idempotent guard). Logs
    show `redis_event_bus: bridge crashed: <reason>`.

## Testing

`services/api/tests/test_r1_redis_event_bus.py` (8 tests) pins
the contract:

  * `publish + recent` shape (in-order, dedup, ring-size cap).
  * **The R1 win:** `test_publish_on_bus_a_reaches_subscriber_on_bus_b`
    — two independent `RedisEventBus` instances on a shared
    fakeredis; bus A publishes; bus B's subscriber receives.
  * Two subscribers on the same bus both receive.
  * Subscribe replays the ring buffer before going live.
  * Unsubscribe stops delivery.

Tests use `fakeredis` with a shared `FakeServer` (sync + async
clients see the same data) — no real Redis required.

## Backward compatibility

R1 is **fully backwards-compatible**:

  * `from app.services.event_bus import bus` still works (the
    `bus` symbol re-exports the in-process singleton by default).
  * All 23 F8 tests pass unchanged.
  * `DIVIDE_EVENT_BUS` defaults to `memory`, so deployments
    that don't set the env var see exactly the F8 behavior.
  * No DB migration, no API change, no portal change.

## What's deferred to R1.3 / R1.x

  * **R1.3** — operational runbook (`docs/R1-MULTIWORKER.md`,
    this file) + a multi-worker smoke test that boots two
    uvicorn workers + drives a publish/subscribe through curl.
  * **R1.x** — per-run channel sharding if fan-out gets too
    noisy at 100+ concurrent runs. Not currently on the path.

## See also

  * [`docs/PLAN.md` §17 + §18.2](PLAN.md) — the F9 + R1
    roadmap; F9 already shipped, R1 lands here.
  * [`docs/F8-SOC.md`](F8-SOC.md) — F8 (SOC view + SSE) —
    the source of the EventBus + the SSE handler that R1 makes
    multi-worker safe.
  * [`docs/SECTION-9-INTEGRATION.md`](SECTION-9-INTEGRATION.md)
    — F9 (DrillConsole consolidation) — uses the same
    `SocViewCard` that R1 makes cross-worker-safe.
