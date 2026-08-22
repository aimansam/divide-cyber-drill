# div:ide — Cyber Drill Platform

## Design & Architecture Plan

> **Status:** Phase 0 — Foundations (in progress; control-plane skeleton).
> **Target platform:** Proxmox VE (main host).
> **Control plane runtime:** Docker Compose on a dedicated VM/LXC.
> **Repo root:** `/DATA/Storage/docker/divide-cyber-drill`

---

## 0. Visual Architecture Map

The diagrams below illustrate how div:ide is composed at every phase. Regenerate them with:

```bash
python3 tools/gen_diagrams.py   # writes docs/images/*.png
```

| Diagram | Description |
|---|---|
| [`images/00-overview.png`](images/00-overview.png) | End-state view: control plane, drill SDN zones, Proxmox VM inventory |
| [`images/01-phase0-foundations.png`](images/01-phase0-foundations.png) | **Phase 0** — minimal runnable skeleton, control plane + Proxmox API client |
| [`images/02-phase1-one-vm-drill.png`](images/02-phase1-one-vm-drill.png) | **Phase 1** — single Ubuntu drill VM (vsftpd 2.3.4), Wazuh auto-enroll |
| [`images/03-phase2-multi-vm-sdn.png`](images/03-phase2-multi-vm-sdn.png) | **Phase 2** — multi-VM drills in isolated VxLAN zones |
| [`images/04-phase3-telemetry-reports.png`](images/04-phase3-telemetry-reports.png) | **Phase 3** — Wazuh correlation + MISP publishing + PDF after-action reports |
| [`images/05-phase4-polish.png`](images/05-phase4-polish.png) | **Phase 4** — RBAC via Keycloak, scheduled drills, scenarios marketplace |

![overview](images/00-overview.png)

---

## 1. Vision

**div:ide cyber drill** is a self-hosted, Proxmox-backed cyber range / drill platform that lets a blue team, red team, or training cohort:

- Spin up **isolated, reproducible attack/defense scenarios** on demand.
- Launch scenarios as **isolated VMs** (Kali attacker, victim Linux/Windows, vulnerable services) inside Proxmox.
- Stream telemetry to **Wazuh** (already deployed) and tag indicators in **MISP** (already deployed).
- Run scheduled drills, capture artifacts, and produce **after-action reports**.

The platform is **not** a CTF engine and **not** a public cloud range — it's a private, org-internal drill orchestrator with strong isolation between the *control plane* (div:ide itself) and the *exercise network* (drill VMs).

Naming rationale: **div:ide** = "divide" — the act of segmenting networks, dividing red from blue, and isolating blast radius.

---

## 2. Top-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Proxmox VE (main host)                        │
│                                                                         │
│  ┌─────────────────────── Control Plane (Docker, mgmt VLAN) ──────────┐ │
│  │  div:ide-portal │ div:ide-api │ div:ide-orchestrator │ postgres   │ │
│  │  keycloak       │ minio       │ wazuh-* (existing)   │ misp (ex.) │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─────────────────────── Drill Networks (Proxmox SDN/VLAN) ──────────┐ │
│  │  Range A: blue-team-net ──┐                                         │
│  │  Range B: red-team-net  ──┼── vnets/segments, isolated per drill   │
│  │  Range C: target-net    ──┘                                         │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│  ┌─────────────────────── Proxmox VM/CT inventory ─────────────────────┐│
│  │  Templates: tpl-kali, tpl-win11-vuln, tpl-ubuntu-srv, tpl-pfsense  ││
│  │  Cloned per drill via cloud-init + linked clones                    ││
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

Three logical layers, all sitting on one Proxmox host (later: a cluster):

1. **Control Plane** — div:ide services + existing Wazuh/MISP. Lives on a *management* network that drill VMs cannot reach directly.
2. **Drill Networks** — per-drill or per-range SDN zones. Created/destroyed by div:ide via Proxmox API.
3. **Workload VMs** — the actual Kali, Windows, Linux, firewall VMs cloned from templates.

---

## 3. Tech Stack

| Concern | Choice | Why |
|---|---|---|
| Orchestration backend | **Proxmox VE 8.x** | Already your hypervisor; rich REST API; supports cloud-init, SDN, snapshots, linked clones |
| Control plane runtime | **Docker Compose** (v2) on a Debian/PVE VM or LXC | Matches your existing stacks (wazuh-docker, misp-docker) |
| Frontend | **Next.js (React, TypeScript)** | Fast iteration, good for forms/dashboards; SPA deployed via `nginx` container |
| API | **FastAPI (Python 3.12)** | Async, OpenAPI auto-generated, easy Proxmox client integration |
| Database | **PostgreSQL 16** | Drill definitions, runs, users, audit log |
| Cache / queue | **Redis** | Job queue for provisioning tasks (RQ/Celery-free, simple) |
| Object storage | **MinIO** | Drill artifacts (PCAPs, screenshots, logs, reports) |
| Identity | **Keycloak** (OIDC/SAML) | SSO, RBAC (admin / lead / blue / red / observer) |
| VM provisioning | **proxmoxer** (Python) + `qm cloud-init` | Native API client |
| VM console access | **noVNC + Apache Guacamole** in Docker | Browser-based, no client install for trainees |
| Telemetry / SIEM | **Wazuh** (existing stack) | Agent-based + syslog ingest from drill VMs |
| Threat intel | **MISP** (existing stack) | Auto-publish IOCs extracted from drill runs |
| Observability of div:ide itself | **Prometheus + Grafana + Loki** | Standard, lightweight |
| Secrets | **SOPS** + age, mounted | Avoid hard-coded creds |
| IaC | **Ansible** playbooks for VM post-provision config | Repeatable drill prep |

---

## 4. Repository Layout

```
divide-cyber-drill/
├── README.md
├── docs/
│   ├── PLAN.md                  # this document
│   ├── ARCHITECTURE.md          # diagrams, network map
│   ├── DRILL-LIFECYCLE.md       # state machine
│   ├── SECURITY-MODEL.md        # isolation, blast radius
│   └── RUNBOOKS/                # operator guides
├── deploy/
│   ├── docker-compose.yml       # control-plane services
│   ├── docker-compose.observability.yml
│   ├── .env.example
│   └── traefik/                 # reverse proxy + TLS
├── services/
│   ├── api/                     # FastAPI
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── routers/
│   │   │   ├── core/
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   └── services/
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   ├── orchestrator/            # background workers (RQ)
│   ├── portal/                  # Next.js UI
│   └── guacamole/               # noVNC/Guac stack
├── proxmox/
│   ├── terraform-templates/     # cloud-init snippets
│   ├── vm-templates/            # Packer/import scripts for tpl-*
│   ├── sdn/                     # zone/vnet definitions
│   └── ansible/
├── scenarios/
├── tools/
│   ├── gen_diagrams.py          # architecture diagram generator
│   └── report-builder/          # builds PDF AAR from artifacts
├── tests/
└── .github/
    └── workflows/
```

---

## 5. Core Components

### 5.1 div:ide-api (FastAPI)

- REST + WebSocket.
- Endpoints: `/healthz`, `/readyz`, `/api/v1/{scenarios,drills,proxmox}`.
- Phase 0: stubs only. Phase 1+ implements real behavior.
- RBAC: admin, drill-lead, blue, red, observer.
- Audit log: every API call written to Postgres + shipped to Wazuh.

### 5.2 div:ide-orchestrator (workers)

- Pulls provisioning jobs from Redis queue.
- Steps for a drill:
  1. Reserve Proxmox resources (CPU/RAM/storage pool).
  2. Create SDN zone / VNet for the drill.
  3. Clone VMs from templates (linked clone, fast).
  4. Apply cloud-init user-data.
  5. Boot, wait for `cloud-init` done signal.
  6. Run Ansible playbooks to install scenario services / vulnerabilities.
  7. Register Wazuh agents.
  8. Start PCAP collector sidecar on a span port.
  9. Notify portal via WebSocket.
  10. Schedule teardown (TTL or manual).

### 5.3 div:ide-portal (Next.js) — Phase 1+

- Pages: Dashboard, Scenarios, Drills (live), Reports, Admin, Audit.
- Live console: embeds noVNC iframe from Guacamole.

### 5.4 Scenario Engine — Phase 1+

A drill is described declaratively (see [`scenarios/`](../../scenarios/) for the schema once it lands).

---

## 6. Proxmox Integration (gated behind credentials)

### 6.1 Templates (built in Phase 1+)

| VMID | Name | Notes |
|---|---|---|
| 9000 | `tpl-kali` | cloud-init, qemu-guest-agent |
| 9001 | `tpl-win2022` | Sysmon + Wazuh agent |
| 9003 | `tpl-ubuntu-2204` | cloud-init, vulnerable service profiles per scenario |
| 9004 | `tpl-pfsense` | OVA import |
| 9005 | `tpl-tinycore` | PCAP collector |

Linked clones from a template take ~5–15 s vs. full clone ~1–3 min.

### 6.2 Cloud-init (Phase 1+)

Each drill VM gets a unique `ciuser` / `sshkeys`, plus per-scenario `user-data` baked by the orchestrator.

### 6.3 Networking (Phase 2+)

Proxmox SDN with VxLAN zones, one per drill. Control-plane bridge is *not* attached to any drill VNet.

### 6.4 Quotas & Safety

- Per-drill resource cap (default: 4 vCPU / 8 GB RAM / 50 GB disk).
- Hard TTL: drills auto-teardown after N hours (default 4 h, max 24 h).
- Pre-drill guard: refuse if remaining host capacity < 25%.

---

## 7. Drill Lifecycle (state machine)

```
DRAFT ──submit──> SCHEDULED ──worker pick──> PROVISIONING ──ready──> LIVE
   │                                                       │           │
   │                                                       │           ├── pause ──> PAUSED
   │                                                       │           ├── inject ──> LIVE (with event)
   │                                                       │           └── ttl ──> TEARING_DOWN
   │                                                       │
   └────────────────── cancel anytime ◄────────────────────┘
                                                           ▼
                                                       COLLECTING
                                                           ▼
                                                        REPORTED
                                                           ▼
                                                       ARCHIVED
```

Persisted as `drills.status` in Postgres; every transition appends to `drill_events` (audit trail) and is forwarded to Wazuh.

---

## 8. Integration with Existing Stacks

### 8.1 Wazuh (Phase 1+)

A Wazuh agent group per drill (e.g. `drill-<id>`). div:ide-api creates/deletes the group via Wazuh API when a drill starts/ends.

### 8.2 MISP (Phase 3+)

On drill completion, report-builder extracts IOCs (IPs, domains, URLs, hashes) from PCAPs and pushed them to MISP as an event tagged `drill:<id>` and `tlp:amber`.

---

## 9. Security Model

| Boundary | Control |
|---|---|
| Internet ↔ div:ide control plane | Traefik with TLS + fail2ban; only 443/80 exposed |
| Control plane ↔ Proxmox API | Internal network, token auth, scoped Proxmox user |
| Control plane ↔ drill VMs | Routed telemetry VLAN, egress-only firewall |
| Drill VM A ↔ Drill VM B | Separate SDN VxLAN zones — L2 unreachable |
| Drill VM ↔ Internal corporate LAN | Default deny; explicit allowlist |
| Secrets | Age-encrypted `.env` + SOPS; never committed |

---

## 10. Operational Concerns

- **Backups:** Proxmox PBS backs up templates nightly. Drill VMs are ephemeral; their artifacts land in MinIO with lifecycle rule (cold after 30 d, delete after 180 d).
- **Capacity planning:** A typical 4-VM drill ≈ 8 vCPU / 16 GB RAM. On the current 12 GB / 8-core VM you can run at most 1 such drill; on the main Proxmox host target 3–5 concurrent drills.
- **Cost in time:** End-to-end drill boot target: < 3 min from "Start" to "All VMs reachable".

---

## 11. Roadmap

**Phase 0 — Foundations (in progress)**
- ✅ Plan + architecture diagrams
- ✅ Docker Compose control plane (api, postgres, redis, minio, traefik)
- ✅ FastAPI skeleton with `/healthz`, `/readyz`, stub routers
- ✅ Proxmox client (gated, requires explicit env vars)
- ⏳ Main Proxmox integration (next gate)

**Phase 1 — One-VM drill end-to-end** (next)
- Templates: `tpl-ubuntu-2204`.
- Scenario: vsftpd 2.3.4.
- Portal: list scenarios, start drill, see console, see artifact (PCAP), stop drill.
- Wazuh: drill group auto-created.

**Phase 2 — Multi-VM + SDN**
- Add `tpl-kali`, `tpl-win2022`, `tpl-pfsense`.
- Proxmox SDN zones per drill.
- Inject engine.
- Guacamole/noVNC console in portal.

**Phase 3 — Telemetry & reports**
- Wazuh dashboard per drill.
- MISP event publication.
- PDF after-action report.

**Phase 4 — Polish**
- RBAC via Keycloak.
- Scheduled drills (cron).
- Scenarios marketplace (import/export YAML).
- Multi-tenant org support.

---

## 12. Key Decisions to Confirm

1. Single Proxmox host vs. cluster — affects HA and SDN assumptions.
2. Wazuh/MISP integration depth — feed only, or full bidirectional.
3. Auth source — Keycloak from scratch, or hook into an existing IdP.
5. Public exposure — strictly internal LAN, or WireGuard for remote trainees.
5. Scenario scope — start with Linux-only, or include Windows (licensing).
6. Artifact retention — proposed 30 d hot / 180 d cold.
7. Naming & branding — confirm `div:ide` spelling/colons.
8. Where the control plane lives — dedicated PVE VM, LXC, or PVE host.

---

## 13. What We Built First (now in repo)

The minimum runnable skeleton lives at the root of this repo:

1. `deploy/docker-compose.yml` — API (FastAPI), Postgres 16, Redis 7, Traefik, MinIO.
2. `services/api/` — FastAPI skeleton with `GET /healthz`, `GET /readyz`, `POST /drills` (501 stub), `GET /api/v1/proxmox/health` (503 unless Proxmox env set).
3. `services/api/scripts/proxmox-smoke.py` — standalone Proxmox reachability check.
4. `Makefile` — `make up`, `make down`, `make logs`, `make smoke`, `make test`, `make lint`, `make proxmox-ping`, `make diag`.
5. CI: `.github/workflows/ci.yml` runs ruff + mypy + pytest on every PR.
6. Architecture diagrams in `docs/images/` regenerated by `tools/gen_diagrams.py`.

Result: `make up` brings the control plane online in < 60 s and `/healthz` returns 200 with zero Proxmox dependencies.

---

*End of plan. When you're ready, the next gate is Proxmox integration (see §11).*
