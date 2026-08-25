# div:ide cyber drill platform

> **A self-hosted, Proxmox-backed cyber range** that spins up
> isolated, reproducible attack/defense scenarios as VMs,
> streams live telemetry to a SOC view, scores flags with
> time-decay, and produces leadership-ready markdown debriefs.
>
> **Status (F12 shipped):** all five final-product pillars
> closed — F9 (DrillConsole consolidation), R1 (multi-worker
> SSE via Redis pub/sub), F11 (drill debrief artifact),
> F10 (4-step onboarding wizard), F12 (this packaging).
> **891 tests passing** (431 root + 460 API), portal bundle
> 275.76 KB (4.24 KB under the 280 KB ceiling).
>
> See [`docs/PLAN.md`](docs/PLAN.md) §17-§19 for the full
> roadmap + closure summary.

## What it does

`div:ide` is a cyber-range orchestrator for blue teams, red teams,
and training cohorts. An operator with a Proxmox host can:

1. **Describe a scenario as YAML.** Multi-VM, multi-network,
   with planted flags and win conditions. Schema-validated.
2. **Run the scenario on demand.** Clones VMs from cloud-init
   templates, attaches them to per-scenario networks, plants
   flags, watches assets boot.
3. **Watch the live drill in one screen.** The Observe tab
   shows status / topology / assets / VNC console / audit
   feed / leaderboard (live) / SOC stream (live). No tab
   flipping during a multi-team exercise.
4. **Hand leadership a markdown debrief.** One-click "View
   debrief" opens a 7-section play-by-play (summary / per-team
   score / per-flag timing / pivot timeline / detection
   timeline / asset table / lessons learned).
5. **Reset to clean state for the next cohort.** Snapshot the
   current state as a template, clone it for the next run.

The platform ships with four reference scenarios:

| Scenario | Side | Difficulty | Duration |
|---|---|---|---|
| [`first-live-drill`](examples/scenarios/first-live-drill.scenario.yaml) | single-team | beginner | 30 min |
| [`red-vs-blue-baseline`](examples/scenarios/red-vs-blue-baseline.scenario.yaml) | multi-team (red + blue) | beginner | 30 min |
| [`phish-to-ransom`](examples/scenarios/phish-to-ransom.scenario.yaml) | single-team | intermediate | 90 min |
| [`lateral-movement-baseline`](examples/scenarios/lateral-movement-baseline.scenario.yaml) | single-team | beginner | 45 min |

## Five-minute "first drill" walkthrough

The platform ships with a 4-step onboarding wizard. A brand-new
operator with a fresh deployment goes from "empty database" to
"live drill running" in ~2 minutes, all in the browser.

### 1. Install

```bash
git clone <this-repo> divide-cyber-drill
cd divide-cyber-drill

cp deploy/.env.example deploy/.env
# edit deploy/.env -- at minimum change POSTGRES_PASSWORD
# and MINIO_ROOT_PASSWORD. Proxmox creds are set later by the
# setup wizard; no need to fill them in here.

make up             # starts the stack (waits for /healthz)
```

### 2. Open the portal

Browse to `http://localhost:8000/portal/app/`.

The first time you visit, you see the **Onboarding Wizard**
(4 steps). No token, no users yet — the wizard walks you
through:

```
Step 1: Bootstrap admin      POST /api/v1/auth/setup
Step 2: Pick scenario        GET /api/v1/scenarios
Step 3: Form team (multi)    POST /exercises + POST /auth/users
Step 4: Launch drill         POST /api/v1/drills (single-team)
```

### 3. Fill in the wizard

  * **Step 1** — type an admin username (e.g. `alice`) + a
    password (min 8 chars). Click **Create admin**. The wizard
    stashes the token; you're now authenticated as admin.
  * **Step 2** — pick a scenario from the list. Single-team
    scenarios (e.g. `first-live-drill`) skip step 3.
    Multi-team scenarios (e.g. `red-vs-blue-baseline`) advance
    to step 3.
  * **Step 3** — name the red + blue teams (defaults are
    `red` / `blue`). Optionally bulk-add member usernames in
    the textarea (one per line; blank lines skipped). Click
    **Create + launch exercise**.
  * **Step 4** (single-team only) — click **Launch drill**.

### 4. Watch the live drill

The wizard lands you on the **DrillConsole** in the Observe
tab. As the run progresses you'll see:

  * Status header with LIVE pulse badge.
  * Topology graph (SVG, no dep).
  * Asset table with live IPs.
  * VNC console button → opens the asset's console in a new
    tab.
  * Audit feed (live).
  * For multi-team exercises: leaderboard (live, 5 s polling)
    + SOC stream (live, SSE).
  * Duration timer ticking every second.

### 5. Hand off the debrief

When the run is terminal (`succeeded` / `failed` / `timeout` /
`cancelled`), the **View debrief** button appears in the header.
Click it to open the markdown play-by-play in a new browser
tab. Use **Download report** for the JSON sibling (full run
metadata + asset list + audit timeline + Prometheus metrics).

## What's in the box

```
divide-cyber-drill/
├── services/
│   ├── api/                          FastAPI control plane
│   │   ├── app/
│   │   │   ├── routers/              /api/v1/* endpoints (27 routers)
│   │   │   ├── db/models.py          11 tables, 6 migrations
│   │   │   ├── runners/              RealProxmoxAdapter + MockProxmoxAdapter
│   │   │   ├── services/             auth, scenario_sync, event_bus (Redis + in-process)
│   │   │   └── observability/        Prometheus metrics
│   │   ├── tests/                    460 API tests
│   │   └── pyproject.toml
│   └── portal/app/                   React + Vite portal (CDN-style)
│       ├── src/components/portal/    20+ components (cards)
│       └── build/                    vite bundle (275.76 KB)
├── deploy/
│   ├── docker-compose.yml            Dev stack (single-worker)
│   ├── docker-compose.production.yaml  F12.3 production stack (multi-worker + Redis)
│   ├── traefik/                      TLS termination in prod
│   ├── prometheus/                   metrics scrape config
│   └── grafana/                      dashboards
├── examples/
│   ├── scenarios/                    4 reference scenarios
│   └── demo-output.md                F12.2 captured walkthrough
├── schemas/
│   └── scenario.schema.json          JSON Schema for /api/v1/scenarios
├── tools/                            Operator CLI (issue_token, demo, verify_drill, ...)
├── docs/
│   ├── PLAN.md                       Canonical roadmap + closure summaries
│   ├── TEST-PRODUCT.md               L1/L2/L3 ship criteria
│   ├── SECTION-9-INTEGRATION.md      F9 DrillConsole consolidation
│   ├── SECTION-10-ONBOARDING.md      F10 onboarding wizard
│   ├── R1-MULTIWORKER.md             R1 Redis multi-worker SSE
│   ├── F8-SOC.md                     F8 SOC view + SSE
│   ├── ...                           (15+ runbooks)
│   └── images/                       Architecture diagrams
└── Makefile                          `make up`, `make verify`, `make demo`, ...
```

## Features at a glance

  * **5 final-product pillars** shipped (F9, R1, F10, F11, F12)
    + 8 cyber-range plans (F3-F8) + 18 L2 ledger items + 9 L1
    ledger items. See [`docs/PLAN.md`](docs/PLAN.md) §15.6 +
    §17 + §18.
  * **Multi-team exercises** (F6): per-team parallel runs on
    a shared scenario topology, live leaderboard.
  * **Live SOC view** (F8): SSE event stream, kill-chain
    timeline, severity filter, pause/resume.
  * **Range templates** (F7): snapshot a finished run as a
    template; clone + reset for the next cohort.
  * **Drill console** (F4-UI): single-screen live-drill view
    with leaderboard + SOC stream inline (F9).
  * **Multi-worker SSE** (R1): Redis pub/sub fan-out so SSE
    events cross uvicorn workers.
  * **Drill debrief** (F11): 7-section markdown play-by-play
    for leadership hand-off.
  * **Onboarding wizard** (F10): 4-step first-time UX in the
    browser. No `tools/issue_token.py` required for first-time
    operators.
  * **Bundle budget** (F9.3): `make verify-bundle` enforces
    the 280 KB ceiling; current bundle is 275.76 KB.
  * **Secure by default**: argon2id password hashes, HMAC
    tokens with TTL, RBAC on every endpoint, rate-limit on
    `POST /drills`, audit log on every state transition,
    polymorphic audit FKs that survive cascade deletes.

## Production deployment

For a single-tenant production deployment with TLS + multi-worker
+ Redis pub/sub + Authentik in production mode, see
[`deploy/docker-compose.production.yaml`](deploy/docker-compose.production.yaml)
and [`docs/SECTION-12-PRODUCTION.md`](docs/SECTION-12-PRODUCTION.md).

Required env vars for multi-worker:

```yaml
environment:
  DIVIDE_EVENT_BUS: redis            # R1: SSE across workers
  DIVIDE_REDIS_URL: redis://redis:6379/0
  DIVIDE_BOOTSTRAP_ADMIN_SUB: ...    # first admin (idempotent)
  DIVIDE_BOOTSTRAP_ADMIN_PASSWORD: ...
```


## Running tests

```bash
make test           # 891 tests across api/ + root
make lint           # ruff + mypy
make verify         # 5-step gate: lint + test + preflight + smoke + bundle-budget
make verify-bundle  # F9.3: portal bundle under 280 KB
```

The default `make test` runs against SQLite. For Postgres:

```bash
make test-live-pg   # requires DIVIDE_TEST_LIVE_PG=1 + a reachable DB
```

## Documentation index

| Doc | Audience | Topic |
|---|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Everyone | Canonical roadmap + closure summaries |
| [`docs/TEST-PRODUCT.md`](docs/TEST-PRODUCT.md) | Devs | L1/L2/L3 ship criteria |
| [`docs/SECTION-9-INTEGRATION.md`](docs/SECTION-9-INTEGRATION.md) | Operators | F9 DrillConsole consolidation (single live-drill screen) |
| [`docs/SECTION-10-ONBOARDING.md`](docs/SECTION-10-ONBOARDING.md) | Operators | F10 onboarding wizard (4-step first-time UX) |
| [`docs/SECTION-11-DEBRIEF.md`](docs/SECTION-11-DEBRIEF.md) | Operators | F11 drill debrief (markdown play-by-play) |
| [`docs/SECTION-12-PRODUCTION.md`](docs/SECTION-12-PRODUCTION.md) | Operators | F12 production deployment (TLS + multi-worker) |
| [`docs/R1-MULTIWORKER.md`](docs/R1-MULTIWORKER.md) | Devs | R1 Redis multi-worker SSE |
| [`docs/F3-RUNBOOK.md`](docs/F3-RUNBOOK.md) | Devs | F3 multi-VM scenarios |
| [`docs/F4-NOVNC.md`](docs/F4-NOVNC.md) | Devs | F4 noVNC console |
| [`docs/F5-SCORING.md`](docs/F5-SCORING.md) | Devs | F5 flag scoring |
| [`docs/F6-MULTITEAM.md`](docs/F6-MULTITEAM.md) | Devs | F6 multi-team exercises |
| [`docs/F7-TEMPLATES.md`](docs/F7-TEMPLATES.md) | Devs | F7 range templates |
| [`docs/F8-SOC.md`](docs/F8-SOC.md) | Devs | F8 SOC view + SSE |
| [`docs/PORTAL-APP.md`](docs/PORTAL-APP.md) | Frontend devs | Portal component inventory |
| [`docs/PORTAL-UI.md`](docs/PORTAL-UI.md) | Designers | Visual layout + tab nav |
| [`docs/LIVE-DRILL-RUNBOOK.md`](docs/LIVE-DRILL-RUNBOOK.md) | Operators | Live drill command reference |
| [`docs/DEMO.md`](docs/DEMO.md) | Operators | Demo flow notes |
| [`docs/PROXMOX-SETUP.md`](docs/PROXMOX-SETUP.md) | Operators | Proxmox token + ACL setup |
| [`docs/USERS.md`](docs/USERS.md) | Operators | Credential auth model |
| [`docs/SCENARIO-SPEC.md`](docs/SCENARIO-SPEC.md) | Scenario authors | YAML schema reference |
| [`docs/SCENARIO-SYNC.md`](docs/SCENARIO-SYNC.md) | Devs | YAML -> DB sync |
| [`docs/SETUP-UI.md`](docs/SETUP-UI.md) | Operators | Setup wizard at `/portal/` |
| [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) | Operators | Prometheus + Grafana setup |

## Roadmap

All five final-product pillars (PLAN.md §17) shipped in 2026:

| # | Pillar | Commits |
|---|---|---|
| **F9** | DrillConsole consolidation — leaderboard + SOC inline | `cbd181e`, `aeba832`, `2004e83` |
| **R1** | Multi-worker SSE via Redis pub/sub | `19d5cce`, `86020ef` |
| **F11** | Drill debrief artifact (markdown) | `3683480`, `64256e1`, `b0b3cea` |
| **F10** | Onboarding wizard (4-step) | `2ab897a`, `a8db813`, `68d7f15` |
| **F12** | Product packaging (this commit) | `...` |

Backlog (PLAN.md §19): R2 (light theme + mobile + keyboard shortcuts),
R3 (coaching / replay mode), R4 (range bookings calendar), R5
(multi-tenant isolation), R6 (scenario marketplace), R7 (replay UI
with playhead). Total ~34 h. No committed delivery date.

## Architecture

```
+------------------+       +-------------------+       +------------------+
| Proxmox VE host  |       | Traefik (TLS)     |       | div:ide portal   |
| (PVE 9.x)        | <---> | (prod only)       | <---> | /portal/app/     |
|                  |       |                   |       | (React + Vite)   |
| +--------------+ |       +-------------------+       +------------------+
| | tpl-debian   | |                  |                          ^
| | tpl-kali     | |                  |                          |
| | tpl-pfsense  | |                  v                          |
| +--------------+ |       +-------------------+                  |
| | cloned VMs   | |       | div:ide API       |                  |
| | (drill)      | | <---> | (FastAPI +        | <----------------+
| +--------------+ |       |  uvicorn workers) |
+------------------+       |                   |
                            +---------+---------+
                                      |
                                      v
                  +-----------+-----------+-----------+
                  |                       |           |
                  v                       v           v
            +----------+           +-----------+   +--------+
            | Postgres |           | Redis     |   | MinIO  |
            | (state)  |           | (cache +  |   | (artif-|
            +----------+           |  pub/sub) |   | acts)  |
                                   +-----------+   +--------+
```

For full architecture diagrams, see [`docs/images/`](docs/images/).

## Status codes

All API endpoints follow the standard FastAPI conventions:

  * `200` / `201` — success.
  * `400` — bad request (malformed body).
  * `401` — no token.
  * `403` — token can't see the resource.
  * `404` — not found.
  * `409` — conflict (e.g., exercise already started, run
    not terminal for debrief).
  * `422` — validation error.
  * `429` — rate-limited.
  * `503` — upstream unavailable (PVE unreachable).

## License

MIT — see [`LICENSE`](LICENSE).

## Contributing

Bug reports + PRs welcome. The platform is built on:

  * **Backend**: Python 3.12, FastAPI, SQLAlchemy (async),
    Pydantic, Alembic, redis-py, websockets.
  * **Frontend**: React 18, Vite 6, TypeScript, TailwindCSS,
    Lucide icons. Bundle ceiling: 280 KB.
  * **Infra**: Docker Compose, Traefik (prod), PostgreSQL,
    Redis, MinIO.

Before opening a PR:

```bash
make verify    # lint + test + preflight + smoke + bundle-budget
```
