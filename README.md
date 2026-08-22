# div:ide cyber drill

> **Status:** Phase 0 — Foundations. Control-plane skeleton only.
> See [`docs/PLAN.md`](docs/PLAN.md) for the full design and roadmap.

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
│   ├── PLAN.md                  # full design + architecture
│   └── images/                  # 6 architecture diagrams (auto-generated)
├── deploy/
│   ├── docker-compose.yml       # control-plane stack
│   ├── .env.example             # template for .env
│   └── traefik/                 # static traefik config
├── services/
│   ├── api/                     # FastAPI app
│   │   ├── app/                 # code
│   │   ├── tests/               # pytest
│   │   ├── scripts/             # proxmox-smoke.py
│   │   └── Dockerfile
│   └── ...                      # orchestrator/portal/guacamole land in later phases
├── tools/
│   └── gen_diagrams.py          # regenerates docs/images/*.png
├── scripts/
│   ├── dev-shell.sh             # `make shell`-style helper
│   └── lint-all.sh              # `make lint`-style helper
├── Makefile
├── pyproject.toml               # ruff + mypy config
└── .pre-commit-config.yaml
```

---

## Quickstart (Phase 0)

Requirements: Docker 24+, Docker Compose v2, Python 3.12 (only for lint/test).

```bash
git clone <this-repo> divide-cyber-drill
cd divide-cyber-drill

cp deploy/.env.example deploy/.env
# edit deploy/.env — at minimum change POSTGRES_PASSWORD and MINIO_ROOT_PASSWORD

make build          # build the API container
make up             # start the stack (waits for /healthz)
make smoke          # curl the health, ready, and stub endpoints
make logs           # tail logs
```

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

| Phase | What | When |
|------:|------|------|
| 0     | **You are here.** Control-plane skeleton + Proxmox client (unused) | now |
| 1     | One-VM drill end-to-end (vsftpd scenario, tpl-ubuntu-2204)        | ~2 wk |
| 2     | Multi-VM drills in isolated VxLAN zones                            | ~3 wk |
| 3     | Wazuh correlation + MISP publishing + PDF after-action reports    | ~2 wk |
| 4     | RBAC via Keycloak + scheduled drills + scenarios marketplace       | ~2 wk |

Full plan: [`docs/PLAN.md`](docs/PLAN.md).

---

## License

MIT — see [`LICENSE`](LICENSE).
