# div:ide cyber drill

> **Status:** Phase 0 ✅ + Phase 1 ✅ + Phase 2 ✅ (L1 9/9, L2 18/18).
> **§15 cyber-range plans F3-F8 ALL CLOSED** — multi-VM scenarios
> (F3), noVNC console (F4), flag scoring (F5), multi-team exercises
> (F6), range templates (F7), SOC view + SSE telemetry (F8).
> **859 tests passing** (431 root + 428 API).
> See [`docs/PLAN.md`](docs/PLAN.md) §15 for the cyber-range roadmap
> and §17 for the post-§15 follow-ons.
> See [`docs/TEST-PRODUCT.md`](docs/TEST-PRODUCT.md) for the L1/L2/L3 ship criteria.
> Browser tools ship in the API container: setup wizard at `/portal/`,
> operator test tool at `/portal/test/`, full cyber-range portal at `/portal/app/`.

**div:ide** is a Proxmox-backed cyber drill platform for blue teams, red teams, and
training cohorts. It spins up isolated, reproducible attack/defense scenarios as VMs,
streams telemetry to Wazuh, and produces after-action reports.

This repository currently contains the **Phase 0 skeleton**: a Docker Compose control
plane (API + Postgres + Redis + MinIO + Traefik) and a FastAPI service with stub
endpoints. **No Proxmox calls happen yet.**

---

## Scenarios

Cyber drills are described declaratively as **Scenario** YAML files. Two
reference examples ship in [`examples/scenarios/`](examples/scenarios/):

- `phish-to-ransom.scenario.yaml` — phishing → AD compromise → ransomware (intermediate, 90 min)
- `lateral-movement-baseline.scenario.yaml` — SMB/WinRM pivot, blue-team focus (beginner, 45 min)

Files validate against [`schemas/scenario.schema.json`](schemas/scenario.schema.json)
(JSON Schema 2020-12). The validator runs in CI and on every commit via
pre-commit.

```bash
# Validate a single file
make validate-scenarios

# Or directly:
python tools/validate_scenario.py examples/scenarios/phish-to-ransom.scenario.yaml
```

Full spec (every field, every enum): [`docs/SCENARIO-SPEC.md`](docs/SCENARIO-SPEC.md).

## What's in here

```
divide-cyber-drill/
├── docs/
│   ├── PLAN.md                  # full design + architecture (now §14 says "read TEST-PRODUCT for current state")
│   ├── LIVE-DRILL-RUNBOOK.md    # operator runbook for the first live drill
│   ├── PROXMOX-SETUP.md         # PVE host setup (ACLs, tokens, ISO)
│   ├── OBSERVABILITY.md         # Prometheus + Grafana wiring
│   ├── SCENARIO-SPEC.md         # full scenario YAML spec
│   ├── SCENARIO-SYNC.md         # YAML → DB catalog sync
│   ├── TEST-PRODUCT.md          # **canonical**: L1/L2/L3 ship criteria + ETAs + next plan
│   ├── USER-REQUIREMENTS.md     # persona view: who needs what, what's wired, what's missing
│   ├── SETUP-UI.md              # docs for the browser-based setup wizard at /portal/
│   ├── PORTAL-APP.md            # docs for the React/Vite user portal at /portal/app/
│   ├── TEST-UI.md               # docs for the operator test tool at /portal/test/
│   └── images/                  # 6 architecture diagrams (auto-generated)
├── deploy/
│   ├── docker-compose.yml       # control-plane stack
│   ├── .env.example             # template for .env
│   └── traefik/                 # static traefik config
├── services/
│   ├── api/                     # FastAPI app
│   │   ├── app/                 # code
│   │   │   ├── routers/         # drills, scenarios, proxmox, admin (setup wizard), health
│   │   │   ├── services/        # proxmox client, runner adapters, admin (template builder), scen_sync
│   │   │   └── main.py          # mounts /portal and /portal/test/ via StaticFiles
│   │   ├── tests/               # pytest (276 tests)
│   │   ├── scripts/             # proxmox-smoke.py
│   │   └── Dockerfile
│   └── portal/                  # static HTML+JS pages served by the API
│       ├── index.html           # → /portal/  (setup wizard, 4 steps)
│       └── test/index.html      # → /portal/test/  (operator test tool, 7 cards)
├── tools/                       # CLI entry points used by Makefile targets
│   ├── gen_diagrams.py          # regenerates docs/images/*.png
│   ├── preflight.py             # `make preflight` — 9 PVE/stack health checks
│   ├── upload_cloudinit_template.py  # `make upload-template` — create tpl-debian-cloudinit
│   ├── live_drill.py            # `make live-drill` — POST /api/v1/drills + poll
│   ├── verify_drill.py          # `make verify-drill` — assertions on run outcome (4 checks)
│   ├── watch_drill.py           # `make watch-drill` — Prometheus-driven outcome watcher
│   ├── sync_scenarios.py        # `make sync-scenarios` — YAML → DB
│   └── validate_scenario.py     # `tools/validate_scenario.py` — JSON-Schema check
├── scripts/
│   ├── dev-shell.sh             # `make shell`-style helper
│   └── lint-all.sh              # `make lint`-style helper
├── tests/                       # top-level pytest (preflight, scenarios, smoke, etc.)
├── Makefile
├── pyproject.toml               # ruff + mypy config
└── .pre-commit-config.yaml
```

---

## Quickstart (Phase 0 → L1)

Requirements: Docker 24+, Docker Compose v2, Python 3.12 (only for lint/test).

```bash
git clone <this-repo> divide-cyber-drill
cd divide-cyber-drill

cp deploy/.env.example deploy/.env
# edit deploy/.env — at minimum change POSTGRES_PASSWORD and MINIO_ROOT_PASSWORD,
# and fill in PROXMOX_HOST/PROXMOX_USER/PROXMOX_TOKEN_ID/PROXMOX_TOKEN_SECRET
# from your PVE token (see docs/PROXMOX-SETUP.md §5).

make build          # build the API container
make up             # start the stack (waits for /healthz)
make preflight      # confirm 9/9 PVE + stack health checks pass
make smoke          # curl the health, ready, and stub endpoints
make logs           # tail logs
```

### Three browser tools ship with the API

After `make up` (and `make portal-build` once, for the React one), browse to:

| URL | Audience | Purpose | Doc |
|---|---|---|---|
| `http://localhost:8000/portal/`       | Operator (first run)   | Setup wizard — stand up a fresh PVE-backed deployment without SSH-ing into Proxmox | [`docs/SETUP-UI.md`](docs/SETUP-UI.md) |
| `http://localhost:8000/portal/test/`  | Operator (day-to-day)  | Test tool — every control-plane endpoint as a click button | [`docs/TEST-UI.md`](docs/TEST-UI.md) |
| `http://localhost:8000/portal/app/`   | Trainee + lead         | User portal — sign in, pick a scenario, run a drill, download a debrief (React + Vite) | [`docs/PORTAL-APP.md`](docs/PORTAL-APP.md) |

The first two are vanilla HTML + JS — no build step. The third is a
Vite-built React app; `make portal-build` produces the bundle that
the API container serves (the bind mount in `deploy/docker-compose.yml`
means a rebuild propagates without rebuilding the API image).
All three share FastAPI's `StaticFiles` mount under `/portal/`.
No new containers, no new runtime — just open the URL.

### Running a live drill (L1)

L1 is closed. Run #11 ended `succeeded` (`pve_vmid=109`, audit log
populated, asset teardown to `stopped`). The drill command:

```bash
make live-drill SCENARIO=first-live-drill TIMEOUT=300   # run the drill
make verify-drill                                          # 4/4 checks pass on success
```

For a fresh deploy on a new PVE host, the wizard at `/portal/` walks
through everything (probe, ACL grant, template upload, first drill) in
~10 minutes — no SSH into PVE required except for one `pveum acl modify`
line.

The full runbook is at [`docs/LIVE-DRILL-RUNBOOK.md`](docs/LIVE-DRILL-RUNBOOK.md).

### Current state

- **276 tests passing**, **`make preflight` 9/9**, **L1 ledger: 9 ✅ / 0 ❌ / 0 ⚠️** as of run #11.
- L1 ledger: **9 ✅ / 0 ❌ / 0 ⚠️**. Run #11 (`first-live-drill`) ended
  `succeeded`. See [`docs/TEST-PRODUCT.md`](docs/TEST-PRODUCT.md) for the
  per-criterion progress and the next-5-items plan.
- Phase 0 → L1 complete in code; L1 closures require one live
  drill, which is documented in the runbook above.

Once `make up` succeeds, open:

- API:        http://localhost:8000
- API docs:   http://localhost:8000/docs
- MinIO UI:   http://localhost:9001  (user/pass from .env)
- Traefik:    http://localhost:8080  (if you expose the dashboard port)

---

## Endpoints (Phase 0)

| Method | Path                        | Status        | Purpose |
|--------|-----------------------------|---------------|---------|
| GET    | `/healthz`                  | live          | Liveness probe |
| GET    | `/readyz`                   | live          | Readiness probe (checks Postgres + Redis) |
| GET    | `/api/v1/scenarios`         | live          | Lists scenarios from DB; auto-synced from `examples/scenarios/` |
| POST   | `/api/v1/scenarios`         | live          | Import YAML body or path; validates + upserts |
| GET    | `/api/v1/scenarios/{name}`  | live          | Get one scenario by name |
| DELETE | `/api/v1/scenarios/{name}`  | live          | Soft-archive (sets `archived_at`) |
| POST   | `/api/v1/scenarios/{name}/restore` | live   | Un-archive a previously archived scenario |
| GET    | `/api/v1/drills`            | live          | Lists all runs in DB |
| POST   | `/api/v1/drills`            | live          | Start a drill (`{"scenario_id": N, "started_by": "..."}`) |
| POST   | `/api/v1/drills/{id}/stop`  | live          | Stop + destroy a drill's assets |
| GET    | `/api/v1/proxmox/health`    | gated         | 503 unless `PROXMOX_HOST` + token are set |
| GET    | `/api/v1/proxmox/nodes`     | gated         | Same |

---

## Proxmox integration

**Read-only integration is live in Stage 2.** div:ide can query your Proxmox
for version, nodes, storage pools, and templates — but cannot create, modify,
or delete anything. Token role: `PVEAuditor`.

Setup: see [`docs/PROXMOX-SETUP.md`](docs/PROXMOX-SETUP.md).

### Endpoints

| Method | Path                                       | Returns |
|--------|--------------------------------------------|---------|
| GET    | `/api/v1/proxmox/health`                   | PVE version + release + repoid |
| GET    | `/api/v1/proxmox/nodes`                    | List of cluster nodes |
| GET    | `/api/v1/proxmox/storage`                  | List of storage pools |
| GET    | `/api/v1/proxmox/templates?node=<name>`    | List of VM templates (all nodes by default) |

### Status codes

- `200` — data returned
- `502` — PVE reachable but call failed (auth error, network blip, parse error)
- `503` — Proxmox not configured (env vars missing)

### Quick test

```bash
make restart
curl -s http://localhost:8000/api/v1/proxmox/health
# {"status":"ok","version":"8.x.y","release":"...","repoid":"...","host":"https://..."}
```

### Runner adapter (Stage 5)

The runner uses an internal `ProxmoxAdapter` interface with two implementations:

- `MockProxmoxAdapter` — in-memory fake used by tests and when `PROXMOX_*` env
  vars are missing. Default in dev / CI.
- `RealProxmoxAdapter` — wraps `proxmoxer.ProxmoxAPI` to talk to your live
  PVE (clone / start / stop / destroy). Selected automatically by
  `build_runner()` once `PROXMOX_HOST` + `PROXMOX_TOKEN_ID` +
  `PROXMOX_TOKEN_SECRET` are all set.

No code change is needed to flip mock ↔ real — set the env vars and restart.

## Development

```bash
make test        # run pytest
make lint        # ruff + mypy
make format      # auto-fix + ruff format
```

Regenerate architecture diagrams (requires `matplotlib`):

```bash
pip install matplotlib
python tools/gen_diagrams.py
```

CI runs on every PR — see `.github/workflows/ci.yml`.

---

## Roadmap

| Phase | What | Status |
|------:|------|:------:|
| 0     | Control-plane skeleton + Proxmox client wrapper                       | ✅ done |
| 1     | One-VM drill end-to-end (vsftpd → first-live-drill scenario)          | ✅ code ✅ — needs one live drill run to flip all L1 ✅ |
| 2     | Multi-VM drills in isolated VxLAN zones                              | ❌ not started |
| 3     | Wazuh correlation + MISP publishing + PDF after-action reports      | ❌ not started |
| 4     | RBAC via Keycloak + scheduled drills + scenarios marketplace         | ❌ not started |

**Where we actually are**: between Phase 1 and Phase 2. The L1
acceptance bar from [`docs/TEST-PRODUCT.md`](docs/TEST-PRODUCT.md) is
met end-to-end — all 276 tests pass, `make preflight` reports 9/9, run
#11 succeeded against real PVE (clone → boot → stop → destroy on a
single `drill_vm` asset), and the wizard at `/portal/` covers the
one-shot fresh-deploy path (probe → `pveum` grant → template upload →
first drill).

**Next move** (~2.5 h, no PVE required): close the remaining L2 work
listed in [`docs/TEST-PRODUCT.md` §L2](docs/TEST-PRODUCT.md#l2--trusted-colleague-lan-demo)
— rate-limit on `POST /drills`, drill auto-timeout, MinIO telemetry
sink, after-action JSON report. Once those land: L2 ledger to 15/18
✅, tag `v0.2.0-l2`.

**Optional polish** (~1 h, no PVE required): next-plan item #5
(SSH-key wizard step) so the wizard flips `PVEDatastoreAdmin` itself
and a fresh deploy needs zero SSH into PVE at all. See
[`docs/TEST-PRODUCT.md` §Next plan](docs/TEST-PRODUCT.md#next-plan-post-l1-ordered).

Full design: [`docs/PLAN.md`](docs/PLAN.md). Canonical status ledger:
[`docs/TEST-PRODUCT.md`](docs/TEST-PRODUCT.md).

---

## License

MIT — see [`LICENSE`](LICENSE).
