# div:ide Cyber Drill Platform

A comprehensive cyber drill platform for managing training labs, exercises, and Proxmox VE infrastructure.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User Browser                          │
│                 http://localhost:5000                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Flask Portal (port 5000)                    │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Landing Page (/)                                │  │
│  │  - OxBlood branding and product showcase         │  │
│  │  - Two products: OxBlood Drill & OxBlood Learn   │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Login Page (/login)                             │  │
│  │  - Tabbed interface (Drill active, Learn soon)   │  │
│  │  - OxBlood themed authentication                 │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Drill Platform (/drill/*)                       │  │
│  │  - Dashboard, Labs, Drills, Teams, etc.          │  │
│  │  - Full cyber training platform                  │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │  API Proxy (/api/*)                              │  │
│  │  - Proxies to FastAPI backend                    │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│           FastAPI Backend (internal:8000)                │
│  • REST API endpoints                                   │
│  • Database operations (PostgreSQL)                     │
│  • Proxmox VE integration                               │
│  • Redis event bus                                      │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+
- Python 3.11+ (for backend development)

### 1. Clone and Configure

```bash
git clone <repository-url>
cd divide-cyber-drill

# Copy environment template
cp deploy/.env.example deploy/.env

# Edit configuration
nano deploy/.env
```

Required environment variables:
- `POSTGRES_PASSWORD` - PostgreSQL password
- `MINIO_ROOT_PASSWORD` - MinIO secret key
- `DIVIDE_BOOTSTRAP_ADMIN_SUB` - Initial admin username
- `DIVIDE_BOOTSTRAP_ADMIN_PASSWORD` - Initial admin password
- `PROXMOX_HOST` - Proxmox VE host (optional)
- `PROXMOX_TOKEN_ID` - Proxmox API token (optional)

### 2. Build and Start

```bash
# Start all services (portal serves static files directly - no build step)
docker compose -f deploy/docker-compose.yml up -d

# Wait for services to be healthy
docker compose -f deploy/docker-compose.yml ps
```

Access the portal at: **http://localhost:5000**

### 3. Stop Services

```bash
docker compose -f deploy/docker-compose.yml down
```

## User Flow

1. **Landing Page** (`http://localhost:5000/`)
   - View OxBlood brand story and product overview
   - See two products: OxBlood Drill (active) and OxBlood Learn (coming soon)
   - Click "Enter Platform" on OxBlood Drill card

2. **Login Page** (`http://localhost:5000/login`)
   - Tabbed interface showing OxBlood Drill (active) and OxBlood Learn (disabled)
   - Enter credentials and sign in
   - Redirected to drill platform

3. **Drill Platform** (`http://localhost:5000/drill/`)
   - Access dashboard, labs, drills, teams, scoreboard, reports
   - Full cyber training functionality
   - Logout returns to landing page

## Command Reference

### Docker Compose Commands

| Operation | Command |
|-----------|---------|
| **Start services** | `docker compose -f deploy/docker-compose.yml up -d` |
| **Stop services** | `docker compose -f deploy/docker-compose.yml down` |
| **View logs** | `docker compose -f deploy/docker-compose.yml logs -f` |
| **View specific service logs** | `docker compose -f deploy/docker-compose.yml logs -f api` |
| **Restart API** | `docker compose -f deploy/docker-compose.yml restart api` |
| **Restart Portal** | `docker compose -f deploy/docker-compose.yml restart portal` |
| **Rebuild images** | `docker compose -f deploy/docker-compose.yml build` |
| **View running services** | `docker compose -f deploy/docker-compose.yml ps` |
| **Clean up (remove volumes)** | `docker compose -f deploy/docker-compose.yml down -v` |

### Frontend Development

```bash
cd services/portal/app

No build step — edit files in `services/portal/app/` directly and hard-refresh.
```

The portal serves static HTML/CSS/JS directly. Changes are reflected on browser refresh.

### Backend Development

```bash
cd services/api

# Install dependencies
pip install -e .

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest tests/

# Lint code
ruff check .
ruff format .
```

### Database Migrations

```bash
# Run migrations (inside API container)
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head

# Rollback last migration
docker compose -f deploy/docker-compose.yml exec api alembic downgrade -1

# Create new migration
docker compose -f deploy/docker-compose.yml exec api alembic revision --autogenerate -m "description"
```

### Smoke Tests

```bash
# Run end-to-end smoke test (in-memory DB + MockProxmoxAdapter)
docker compose -f deploy/docker-compose.yml run --rm api python /workdir/tools/run_smoke.py
```

### Live Drill Testing

```bash
# Run a live drill against Proxmox VE
docker compose -f deploy/docker-compose.yml run --rm api python /workdir/tools/live_drill.py --scenario first-live-drill --timeout 300
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| **Portal** | 5000 | Flask frontend (landing, login, drill platform) + API proxy |
| **API** | 8000 (internal) | FastAPI backend |
| **PostgreSQL** | 5432 (internal) | Database |
| **Redis** | 6379 (internal) | Event bus & cache |
| **MinIO** | 9000 (internal), 9001 (console) | Object storage |
| **Prometheus** | 9090 | Metrics collection |
| **Grafana** | 3000 | Metrics visualization |
| **Traefik** | - | Service discovery & ACME |
| **WG-Easy** | 51820/udp, 51821 | WireGuard VPN management |

## API Documentation

Once the API is running, access the auto-generated documentation:

- **Swagger UI**: http://localhost:5000/api/docs
- **ReDoc**: http://localhost:5000/api/redoc
- **OpenAPI JSON**: http://localhost:5000/api/openapi.json

## Development Workflow

### Landing Page / Login Page Changes

1. Edit files in `services/portal/app/`:
   - `landing.html` - Landing page
   - `landing.css` - OxBlood theme styles
   - `login.html` - Login page with tabbed interface
   - `login.js` - Login authentication logic
3. Restart portal: `docker compose -f deploy/docker-compose.yml restart portal`
4. Refresh browser (changes are bind-mounted)

### Drill Platform Changes

1. Edit files in `services/portal/app/`:
   - `index.html` - Main drill platform HTML
   - `app.js` - Main application logic
   - `styles.css` - Drill platform styles
   - `pages/*.html` - Individual page templates
2. No build step - files are served directly
3. Refresh browser (changes are bind-mounted)

### Backend Changes

1. Edit files in `services/api/app/`
2. Rebuild API image: `docker compose -f deploy/docker-compose.yml build api`
3. Restart API: `docker compose -f deploy/docker-compose.yml restart api`

### Full Rebuild

```bash
# Stop and remove everything
docker compose -f deploy/docker-compose.yml down -v

# Rebuild all images
docker compose -f deploy/docker-compose.yml build --no-cache

# Start fresh
docker compose -f deploy/docker-compose.yml up -d
```

## Troubleshooting

### Portal not loading

```bash
# Check portal logs
docker compose -f deploy/docker-compose.yml logs portal

# Verify static files exist
ls -la services/portal/app/

# Restart portal
cd deploy && docker compose restart portal
```

### Login not working

```bash
# Check portal logs
docker compose -f deploy/docker-compose.yml logs portal

# Verify API is accessible
curl http://localhost:5000/api/healthz

# Check API logs
docker compose -f deploy/docker-compose.yml logs api
```

### Drill platform not loading

```bash
# Check portal logs
docker compose -f deploy/docker-compose.yml logs portal

# Verify drill files exist
ls -la services/portal/app/pages/

# Restart portal
docker compose -f deploy/docker-compose.yml restart portal
```

### API not responding

```bash
# Check API logs
docker compose -f deploy/docker-compose.yml logs api

# Verify API health
curl http://localhost:5000/api/healthz

# Restart API
docker compose -f deploy/docker-compose.yml restart api
```

### Database connection issues

```bash
# Check PostgreSQL logs
docker compose -f deploy/docker-compose.yml logs postgres

# Verify database is running
docker compose -f deploy/docker-compose.yml ps postgres
```

## Project Structure

```
divide-cyber-drill/
├── deploy/
│   ├── docker-compose.yml    # Service orchestration
│   ├── .env.example          # Environment template
│   ├── prometheus/           # Prometheus config
│   └── grafana/              # Grafana dashboards
├── services/
│   ├── api/                  # FastAPI backend
│   │   ├── app/
│   │   │   ├── routers/      # API endpoints
│   │   │   ├── services/     # Business logic
│   │   │   ├── db/           # Database models
│   │   │   └── runners/      # Proxmox adapters
│   │   └── tests/            # API tests
│   └── portal/               # Flask portal
│       ├── app/              # Static frontend (no build step)
│       │   ├── landing.html  # Landing page
│       │   ├── landing.css   # OxBlood theme
│       │   ├── login.html    # Login page (tabbed)
│       │   ├── login.js      # Login logic
│       │   ├── index.html    # Drill platform main
│       │   ├── pages/        # Drill page templates
│       │   └── *.js          # JavaScript modules
│       ├── flask_app.py      # Flask reverse proxy
│       └── Dockerfile        # Portal container
├── examples/
│   └── scenarios/            # Drill scenario definitions
└── tools/                    # Utility scripts
```

## OxBlood Brand

**OxBlood** stands for: **O**perational e**x**ercises & **Blood** benchmarking for live offensive operations and defense.

The platform embodies three core principles:
- **Operational Excellence** - Real-world adversary tactics, techniques, and procedures
- **Benchmarking Standards** - Objective metrics to track team progress
- **Live Operations** - Hands-on experience with actual offensive and defensive scenarios

## License

Proprietary - All rights reserved.

## Support

For issues and questions, please open an issue in the repository.
---

# OxBlood Documentation (merged from `docs/`, Sep 2026)

**OxBlood — Operational Exercises & Benchmarking for Live Offensive Operations & Defense.**

> All former `docs/*.md` content is now distilled here. Full database schema
> (`DATABASE-SCHEMA.md` + `schema.sql`) is inlined verbatim at the end.
> The 13 git-tracked files under `docs/` were removed in this change — see git history (`git log -- docs/`). Working-tree-only guides (admin/API/roles/flows/scoring/etc.) were distilled above before removal, and the full schema is inlined below.

## Table of Contents

- [1. Vision & Problems Solved](#1-vision--problems-solved)
- [2. Roles & Permissions](#2-roles--permissions)
- [3. Training Model](#3-training-model-features-modules-drill-flow)
- [4. Labs & Scenario Format](#4-labs--scenario-format)
- [5. Scoring & Benchmarking](#5-scoring--benchmarking)
- [6. Reporting](#6-reporting)
- [7. API Reference (condensed)](#7-api-reference-condensed)
- [8. Operations](#8-operations-admin-guide-condensed)
- [9. Security](#9-security)
- [10. System Architecture (condensed)](#10-system-architecture-condensed)
- [11. Database Schema (full, verbatim)](#11-database-schema-full-verbatim)
- [12. Deployable SQL Schema (full, verbatim)](#12-deployable-sql-schema-full-verbatim)
- [13. Roadmap](#13-roadmap)
- [14. Status & History](#14-status--history)

## 1. Vision & Problems Solved

Three purposes: **Training** (hands-on red/blue/purple ops in real VMs),
**Benchmarking** (objective repeatable metrics across standardized scenarios),
**Assessment** (practical scenario-based evaluation, not multiple choice).
| # | Problem | OxBlood answer |
|---|---------|----------------|
| 1 | Theory-only training, toy labs | Isolated reproducible labs with real infra (VMs, nets, services) mirroring production |
| 2 | No objective skill measurement | Standardized scoring + benchmarking across scenarios |
| 3 | Ad-hoc red-vs-blue coordination | Built-in teams, real-time scoring, auto flag validation, structured flow |
| 4 | No skill-progression visibility | Per-category skill tracking, learning paths, trends |
| 5 | Thin post-exercise feedback | After-action reports: timeline, findings, evidence, severity, recommendations |

**OxBlood vs CTF vs cyber range:** range = infra without content; CTF = content
without infra/benchmarking; OxBlood = real infra + curated scenarios + scoring +
reporting + progression.

Target users: Students/Participants, Instructors, Team Leaders, Administrators,
Observers/Judges, Organizations (companies, universities, training providers).

## 2. Roles & Permissions

One role per user, assigned by admins only, effective immediately, audit-logged.
Admins cannot demote themselves. Server-side enforcement on every request
(UI checks are cosmetic). Hierarchy: Administrator > Instructor/Team Leader >
Student; Observer is a separate read-only track.
| Capability | Student | Instructor | Team Lead | Admin | Observer |
|------------|---------|------------|-----------|-------|----------|
| Labs, drills, submit flags | yes | yes | yes | yes | no |
| View scoreboard / own scores+reports | yes | yes | yes | yes | yes (read-only) |
| Create/edit/archive scenarios+drills | no | yes (own+shared) | drills: no | yes | no |
| Grade, create/export reports | no | yes (assigned) | no | yes | export: yes |
| Manage team members | no | yes | yes | yes | no |
| View all scores/reports | no | scoped | scoped | yes | yes |
| Manage users/roles/config/infra, audit logs | no | no | no | yes | audit view: yes |

API roles: `student, instructor, team_leader, administrator, observer` (DB enum
`user_role`). Auth: `POST /api/v1/auth/login` `{sub, password}` ->
`{token, sub, role, iat, exp}`; header `X-Divide-Token` on all other calls;
`GET /api/v1/me` echoes verified identity + `ttl_remaining_s`;
TTL default 8h (`DIVIDE_LOGIN_TOKEN_TTL_S`); 5 bad attempts/sub/15min -> 429;
bootstrap via `DIVIDE_BOOTSTRAP_ADMIN_SUB` + `DIVIDE_BOOTSTRAP_ADMIN_PASSWORD`.
## 3. Training Model (Features, Modules, Drill Flow)

12 features: Dashboard, Lab Management, Drill Scenarios, Offensive Modules,
Defensive Modules, Team Exercises, Scoreboard, Benchmarking, Reporting,
Learning Paths, Admin Panel, RBAC. 9 modules: Auth, Dashboard, Lab, Drill,
Team, Scoring, Reporting, Notification, Admin (Auth gates all; Lab/Drill feed
Scoring; Scoring feeds Scoreboard/Benchmark/Reports).

9-step drill lifecycle:
`create (instructor) -> join -> teams assigned -> env started -> objectives ->
flag/evidence submit -> scoring -> report -> feedback review`.
States: `idle -> live -> {ended | cancelled} -> archived`
(live ends on timer expiry or all objectives complete).
Typical durations: creation 10-30m, teams 5-15m, provisioning 2-10m,
execution 30-120m, report 1-5m (auto), feedback 15-60m.
Best practice: test scenarios first, balance teams, monitor live, review reports,
use hints sparingly (they cost points).

## 4. Labs & Scenario Format

Scenario = blueprint (`divide/v1`, `kind: Scenario`): metadata (name, title,
version, difficulty, duration, tags, authors) + spec (objectives red/blue, infra
networks/assets/topology, flags, scoring, telemetry, hints). Canonical live copies:
`examples/scenarios/*.scenario.yaml`, JSON schema `schemas/scenario.schema.json`.
Validate before import (names, difficulty enum, CIDRs, templates, unique flag
IDs, connectivity, resources). Import via Admin Panel -> Scenarios (upload/paste
server path). Author rules: start simple, test at target level, document, use
real-world TTPs, progressive hints, version everything.
## 5. Scoring & Benchmarking

`Flag Points = Base x max(0.5, 1 - elapsed/decay_window)`.
Base by difficulty: Beginner 50, Easy 75, Medium 100, Hard 150, Expert 200.
Time multiplier: <25% limit 1.5x, 25-50% 1.2x, 50-75% 1.0x, 75-100% 0.8x, over
limit 0.5x. `Total = (FlagPts x TimeMult) - HintPenalties + ReportBonus +
TeamBonus`. Skill ratings per category (web, network, AD, linux, windows,
forensics, blue-team...), percentile vs global/peer/team/org, badges
(First Blood, Streak, Perfect, Sharpshooter, Defender, Speed Demon, Mastermind,
Champion). Leaderboard ranks by points, then time, then solves.

## 6. Reporting

Sections: Summary (scenario/duration/team/result/score) -> Objectives ->
Findings (severity critical/high/medium/low/info) -> Evidence (screenshots, logs,
command output, pcaps) -> Timeline -> Metrics -> Recommendations -> Instructor
feedback. Pipeline: drill ends -> collect (run/scenario/submissions/audit/
evidence) -> compile -> instructor review/approve -> publish + notify + archive.
Access: student own-only, instructor assigned, team-lead own team, admin+observer
all (observer read-only). Export: `GET /api/v1/drills/{id}/report/export?format=
json|html|markdown|pdf`.
## 7. API Reference (condensed)

Base via portal: `http://localhost:5000/api/...` (portal proxies, query strings
preserved); direct: `http://api:8000/api/...`. Auth header `X-Divide-Token` except
`POST /auth/login`, `GET /auth/setup`, `/healthz`, `/readyz`. Content-Type
`application/json`. Full contract: `/api/openapi.json` + `/api/docs`.

| Group | Key endpoints |
|-------|---------------|
| Auth | `POST /api/v1/auth/login\|logout`, `GET /api/v1/auth/setup`, `GET /api/v1/me`, admin `GET /api/v1/auth/users` |
| Users v2 | profile/badges/activity CRUD under `/api/v2/users/...` |
| Labs v2 | CRUD `/api/v2/labs`, publish, categories/tags/flags/objectives/hints |
| Drills v1+v2 | runs CRUD, lifecycle `start\|pause\|resume\|stop`, participants/teams/announcements, flags, reports + export |
| Teams/Score/Reports | teams, leaderboard, scores, reports |
| Admin/Infra | users, scenarios, service-status, pve-config, audit, proxmox health/nodes/templates, VPN conf |

Errors: 400 body, 401 no/bad token, 403 forbidden, 404 missing, 409 terminal
state, 422 validation, 429 rate-limit, 500 internal.
Rate limits: login 5/min, drill-create 10/min, default 100/min.
## 8. Operations (Admin Guide condensed)

Login at `http://<host>:5000/` (portal). Users: Admin Panel -> Users
(create/edit/disable/delete/roles, bulk ops). Scenarios: import YAML or manual
create, validate, publish/archive. Drills: create from scenario, schedule, assign
teams, start/monitor/stop, review reports. Scoring rules editable per platform or
per scenario. Monitor: service-status (API/DB/Redis/PVE/disk/audit), Prometheus
`:9090`, Grafana `:3000`. Backups: `pg_dump` daily, 30d retention, off-site;
restore via `pg_restore`. Bootstrap: set both `DIVIDE_BOOTSTRAP_ADMIN_SUB/PASSWORD`
once, remove after first login, rotate password.

Key env (`deploy/.env` <- `deploy/.env.example`): `POSTGRES_PASSWORD`,
`MINIO_ROOT_USER/PASSWORD/BUCKET`, `DIVIDE_SCENARIOS_DIR`,
`DIVIDE_SYNC_ON_STARTUP`, `DIVIDE_LOGIN_TOKEN_TTL_S`, Proxmox
`PROXMOX_HOST/PORT/USER/TOKEN_ID/TOKEN_SECRET/VERIFY_SSL`, WireGuard
`WG_HOST/PASSWORD_HASH, DIVIDE_WG_*`, observability `GRAFANA_*`, `ACME_EMAIL`.
## 9. Security

Principles: defense in depth, least privilege, zero trust, secure-by-default,
audit everything. Controls: Argon2id passwords, HMAC-SHA256 JWT + TTL, HTTPS +
`X-Divide-Token`, login rate-limit + 5-strike lockout (15m), server-side RBAC,
parameterized queries, audit log on admin/role/score actions, isolated lab nets
(VLAN/VxLAN, firewall, anti-escape), resource limits, snapshots + auto-cleanup,
encrypted backups, Prometheus/Grafana/Wazuh monitoring. 2FA (TOTP) and token
revocation list are future work. Incident ladder: breach immediate,
unauthorized-access/malware 1h, outage 4h, config 24h.
Deploy checklist: TLS 1.3+HSTS+headers, secrets rotated, debug off, firewall on,
deps scanned, backups tested, DR plan filed.

## 10. System Architecture (condensed)

Layers: Browser -> Flask portal `:5000` (`/`, `/login`, `/drill/*`, `/api/*`
proxy) -> FastAPI `:8000` (routers/services/runners) -> PostgreSQL 16 + Redis 7
+ MinIO; infra Proxmox VE 8+ (KVM, linked/full clones, snapshots); edge Traefik
(TLS/ACME/rate-limit); observability Prometheus/Grafana (+Wazuh SIEM future).
Lab lifecycle: scenario sync -> clone from template -> net provision (VLAN/VxLAN
+ firewall) -> cloud-init -> health probe -> run -> snapshot/report -> cleanup.
Zones: mgmt / services / drill-nets (isolated per run) / VPN (WireGuard via
wg-easy) — no drill-to-mgmt escape. Full 2,442-line design with diagrams and
scaling plan (50 -> 5000+ users) lived in `SYSTEM-ARCHITECTURE.md`
(see git history).
## 11. Database Schema (full, verbatim)

> Source: former `docs/DATABASE-SCHEMA.md` (2,164 lines). Kept complete per operator request.

# OxBlood Database Schema Documentation

Complete database design for the OxBlood cybersecurity training platform.

**OxBlood**: Operational Exercises & Benchmarking for Live Offensive Operations & Defense

---

## Table of Contents

1. [Entity Relationship Design](#1-entity-relationship-design)
2. [Database Tables](#2-database-tables)
3. [SQL Schema](#3-sql-schema)
4. [Example Data](#4-example-data)
5. [Database Design Explanation](#5-database-design-explanation)
6. [Security Considerations](#6-security-considerations)
7. [Future Scalability](#7-future-scalability)

---

## 1. Entity Relationship Design

### 1.1 Main Entities Overview

The OxBlood database consists of **50+ tables** organized into 10 modules:

| Module | Tables | Purpose |
|--------|--------|---------|
| **User Management** | users, user_profiles, sessions, password_reset_tokens, user_activity_logs, badges, user_badges | User accounts, authentication, profiles, achievements |
| **Team Management** | teams, team_memberships, team_invitations, team_statistics | Team creation, membership, invitations, performance tracking |
| **Lab Management** | lab_categories, tags, labs, lab_tags, target_machines, lab_objectives, lab_flags, lab_hints, lab_files | Training labs, scenarios, flags, hints, attachments |
| **Drill Management** | drills, drill_scenarios, drill_participants, drill_teams, drill_objectives, drill_announcements | Cyber drill exercises, participants, teams, objectives |
| **Submission System** | submissions, flag_submissions, evidence_submissions, report_submissions, submission_attempts | Flag captures, evidence uploads, report submissions |
| **Scoring System** | scores, score_history, first_bloods | Points, rankings, time-based scoring, first blood bonuses |
| **Benchmarking System** | benchmarks, benchmark_history | Skill scores by category, overall ratings, progression tracking |
| **Reporting System** | reports, report_findings, evidence | After-action reports, findings, evidence files |
| **Learning Path System** | learning_paths, learning_path_modules, learning_path_labs, user_learning_progress, lab_skills | Structured learning, progress tracking, skill mapping |
| **Admin & Audit** | audit_logs, system_notifications, user_notifications, platform_settings, lab_environment_logs, security_events | System monitoring, audit trails, notifications, security |

### 1.2 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER MANAGEMENT                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  users (1) ──────────< user_profiles (1:1)                                  │
│    │                                                                         │
│    ├──────────────< sessions (1:N)                                          │
│    ├──────────────< password_reset_tokens (1:N)                             │
│    ├──────────────< user_activity_logs (1:N)                                │
│    └──────────────< user_badges (1:N) >──────── badges (1:N)                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 1:N
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TEAM MANAGEMENT                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  teams (1) ─────────< team_memberships (1:N) >──────── users (N:M)          │
│    │                                                                         │
│    ├──────────────< team_invitations (1:N)                                  │
│    └──────────────< team_statistics (1:N)                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ N:M
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LAB MANAGEMENT                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  labs (1) ──────────< lab_tags (N:M) >──────── tags (1:N)                   │
│    │                                                                         │
│    ├──────────────< target_machines (1:N)                                   │
│    ├──────────────< lab_objectives (1:N)                                    │
│    ├──────────────< lab_flags (1:N)                                         │
│    ├──────────────< lab_hints (1:N)                                         │
│    ├──────────────< lab_files (1:N)                                         │
│    └──────────────< lab_skills (1:N)                                        │
│                                                                              │
│  lab_categories (1) ───< labs (N:1)                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 1:N
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             DRILL MANAGEMENT                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  drills (1) ─────────< drill_scenarios (1:N) >──────── labs (N:M)           │
│    │                                                                         │
│    ├──────────────< drill_participants (1:N) >──────── users (N:M)          │
│    ├──────────────< drill_teams (1:N) >──────── teams (N:M)                 │
│    ├──────────────< drill_objectives (1:N)                                  │
│    └──────────────< drill_announcements (1:N)                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 1:N
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SUBMISSION SYSTEM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  submissions (1) ────< flag_submissions (1:N) >──────── lab_flags (N:1)     │
│    │                                                                         │
│    ├──────────────< evidence_submissions (1:N)                              │
│    └──────────────< report_submissions (1:1)                                │
│                                                                              │
│  submission_attempts (standalone) - tracks all flag attempts                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ affects
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SCORING SYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  scores (current scores per user/team per drill)                           │
│    │                                                                         │
│    └──────────────< score_history (1:N) - detailed score changes            │
│                                                                              │
│  first_bloods (tracks first capture of each flag per drill)                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ aggregates
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            BENCHMARKING SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  benchmarks (current skill scores per user)                                │
│    │                                                                         │
│    └──────────────< benchmark_history (1:N) - score progression             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ generates
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             REPORTING SYSTEM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  reports (1) ────────< report_findings (1:N)                               │
│                          │                                                   │
│                          └──────────< evidence (1:N)                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                          LEARNING PATH SYSTEM                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  learning_paths (1) ─< learning_path_modules (1:N)                         │
│                          │                                                   │
│                          └──────────< learning_path_labs (1:N) >── labs     │
│                                                                              │
│  user_learning_progress (tracks user progress through paths)               │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                           ADMIN & AUDIT SYSTEM                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  audit_logs (standalone) - comprehensive audit trail                        │
│  system_notifications (1) ──< user_notifications (1:N)                     │
│  platform_settings (standalone) - system configuration                      │
│  lab_environment_logs (standalone) - VM/network event logs                  │
│  security_events (standalone) - security incident tracking                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Relationship Types

#### One-to-One (1:1)
- **users ↔ user_profiles**: Each user has exactly one profile
- **submissions ↔ report_submissions**: Each report submission links to one submission record

#### One-to-Many (1:N)
- **users → sessions**: One user has multiple sessions
- **users → user_activity_logs**: One user has multiple activity logs
- **users → user_badges**: One user earns multiple badges
- **teams → team_memberships**: One team has multiple members
- **teams → team_invitations**: One team sends multiple invitations
- **labs → lab_objectives**: One lab has multiple objectives
- **labs → lab_flags**: One lab has multiple flags
- **labs → lab_hints**: One lab has multiple hints
- **drills → drill_participants**: One drill has multiple participants
- **drills → drill_teams**: One drill has multiple teams
- **drills → drill_announcements**: One drill has multiple announcements
- **submissions → flag_submissions**: One submission can have multiple flag attempts
- **reports → report_findings**: One report has multiple findings
- **report_findings → evidence**: One finding has multiple evidence items

#### Many-to-Many (N:M)
- **users ↔ teams**: Via team_memberships (users can be in multiple teams, teams have multiple users)
- **users ↔ drills**: Via drill_participants (users can participate in multiple drills, drills have multiple participants)
- **teams ↔ drills**: Via drill_teams (teams can participate in multiple drills, drills have multiple teams)
- **labs ↔ tags**: Via lab_tags (labs can have multiple tags, tags can be on multiple labs)
- **learning_paths ↔ labs**: Via learning_path_labs (paths include multiple labs, labs can be in multiple paths)


---

## 2. Database Tables

### 2.1 Module 1: User Management

#### users
**Purpose:** Main user accounts table storing authentication and role information.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| sub | VARCHAR(255) | NO | - | OAuth subject identifier (unique) |
| username | VARCHAR(100) | NO | - | Unique username |
| email | VARCHAR(255) | NO | - | Unique email address |
| password_hash | VARCHAR(255) | YES | NULL | Argon2id hashed password |
| role | user_role | NO | 'student' | User role enum |
| is_active | BOOLEAN | NO | true | Account active status |
| email_verified | BOOLEAN | NO | false | Email verification status |
| last_login_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Last login timestamp |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Account creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |
| deleted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Soft delete timestamp |

**Constraints:**
- PRIMARY KEY (id)
- UNIQUE (sub)
- UNIQUE (username)
- UNIQUE (email)
- CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$')

**Indexes:**
- idx_users_username (username)
- idx_users_email (email)
- idx_users_role (role)
- idx_users_active (is_active) WHERE deleted_at IS NULL

---

#### user_profiles
**Purpose:** Extended user profile information (bio, social links, preferences).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| full_name | VARCHAR(255) | YES | NULL | User's full name |
| bio | TEXT | YES | NULL | User biography |
| avatar_url | VARCHAR(500) | YES | NULL | Avatar image URL |
| organization | VARCHAR(255) | YES | NULL | Organization name |
| location | VARCHAR(255) | YES | NULL | User location |
| website | VARCHAR(500) | YES | NULL | Personal website |
| github_username | VARCHAR(100) | YES | NULL | GitHub username |
| linkedin_url | VARCHAR(500) | YES | NULL | LinkedIn profile URL |
| skills | JSONB | NO | '[]' | Array of skill tags |
| interests | JSONB | NO | '[]' | Array of interest tags |
| preferences | JSONB | NO | '{}' | User preferences |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (user_id)

---

#### sessions
**Purpose:** Active authentication sessions for users.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| session_token | VARCHAR(255) | NO | - | Unique session token |
| ip_address | INET | YES | NULL | Client IP address |
| user_agent | TEXT | YES | NULL | Browser user agent |
| expires_at | TIMESTAMP WITH TIME ZONE | NO | - | Session expiration time |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Session creation time |
| last_activity_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last activity timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (session_token)

---

#### password_reset_tokens
**Purpose:** Temporary tokens for password reset flows.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| token | VARCHAR(255) | NO | - | Unique reset token |
| expires_at | TIMESTAMP WITH TIME ZONE | NO | - | Token expiration time |
| used_at | TIMESTAMP WITH TIME ZONE | YES | NULL | When token was used |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Token creation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (token)

---

#### user_activity_logs
**Purpose:** Track user actions for analytics and audit purposes.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| action | VARCHAR(100) | NO | - | Action performed |
| resource_type | VARCHAR(50) | YES | NULL | Type of resource affected |
| resource_id | INTEGER | YES | NULL | ID of resource affected |
| ip_address | INET | YES | NULL | Client IP address |
| user_agent | TEXT | YES | NULL | Browser user agent |
| details | JSONB | NO | '{}' | Additional action details |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Action timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE

---

#### badges
**Purpose:** Achievement badge definitions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| name | VARCHAR(100) | NO | - | Unique badge name |
| description | TEXT | NO | - | Badge description |
| icon | VARCHAR(50) | NO | - | Badge icon (emoji or identifier) |
| criteria | JSONB | NO | - | Achievement criteria (JSON) |
| category | VARCHAR(50) | NO | - | Badge category |
| rarity | VARCHAR(20) | NO | 'common' | Badge rarity (common, rare, epic, legendary) |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |

**Constraints:**
- PRIMARY KEY (id)
- UNIQUE (name)

---

#### user_badges
**Purpose:** Track which badges each user has earned.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| badge_id | INTEGER | NO | - | Foreign key to badges |
| earned_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When badge was earned |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (badge_id) REFERENCES badges(id) ON DELETE CASCADE
- UNIQUE (user_id, badge_id)

---

### 2.2 Module 2: Team Management

#### teams
**Purpose:** Team definitions for collaborative exercises.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| name | VARCHAR(100) | NO | - | Team name |
| description | TEXT | YES | NULL | Team description |
| organization | VARCHAR(255) | YES | NULL | Organization name |
| created_by | INTEGER | YES | NULL | Foreign key to users (creator) |
| is_active | BOOLEAN | NO | true | Team active status |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |
| deleted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Soft delete timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL

---

#### team_memberships
**Purpose:** Track which users belong to which teams.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| team_id | INTEGER | NO | - | Foreign key to teams |
| user_id | INTEGER | NO | - | Foreign key to users |
| role | VARCHAR(50) | NO | 'member' | Team role (captain, member, coach) |
| joined_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When user joined |
| is_active | BOOLEAN | NO | true | Membership active status |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (team_id, user_id)

---

#### team_invitations
**Purpose:** Track team invitations sent to users.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| team_id | INTEGER | NO | - | Foreign key to teams |
| invited_by | INTEGER | NO | - | Foreign key to users (inviter) |
| invited_user_id | INTEGER | YES | NULL | Foreign key to users (invitee) |
| email | VARCHAR(255) | YES | NULL | Email for external invites |
| token | VARCHAR(255) | NO | - | Unique invitation token |
| status | VARCHAR(20) | NO | 'pending' | Invitation status |
| expires_at | TIMESTAMP WITH TIME ZONE | NO | - | Invitation expiration |
| responded_at | TIMESTAMP WITH TIME ZONE | YES | NULL | When user responded |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
- FOREIGN KEY (invited_by) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (invited_user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (token)

---

#### team_statistics
**Purpose:** Historical team performance data.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| team_id | INTEGER | NO | - | Foreign key to teams |
| drill_id | INTEGER | YES | NULL | Foreign key to drills |
| total_score | INTEGER | NO | 0 | Total points earned |
| flags_captured | INTEGER | NO | 0 | Number of flags captured |
| objectives_completed | INTEGER | NO | 0 | Number of objectives completed |
| average_time_seconds | INTEGER | YES | NULL | Average completion time |
| rank_position | INTEGER | YES | NULL | Final rank position |
| recorded_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | When recorded |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE


---

### 2.3 Module 3: Lab Management

#### labs
**Purpose:** Training lab and scenario definitions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| name | VARCHAR(255) | NO | - | Unique lab identifier |
| title | VARCHAR(255) | NO | - | Human-readable title |
| description | TEXT | NO | - | Lab description |
| version | INTEGER | NO | 1 | Schema version |
| category_id | INTEGER | YES | NULL | Foreign key to lab_categories |
| difficulty | lab_difficulty | NO | 'beginner' | Difficulty level |
| duration_minutes | INTEGER | YES | NULL | Estimated duration |
| status | lab_status | NO | 'draft' | Lab status |
| is_public | BOOLEAN | NO | false | Public visibility |
| requires_team | BOOLEAN | NO | false | Team requirement |
| min_team_size | INTEGER | YES | NULL | Minimum team size |
| max_team_size | INTEGER | YES | NULL | Maximum team size |
| spec | JSONB | NO | '{}' | Full scenario specification |
| authors | JSONB | NO | '[]' | Author information |
| prerequisites | JSONB | NO | '[]' | Required labs/skills |
| learning_objectives | JSONB | NO | '[]' | Learning outcomes |
| source_path | VARCHAR(500) | YES | NULL | Source YAML file path |
| published_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Publication time |
| archived_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Archive time |
| created_by | INTEGER | YES | NULL | Foreign key to users (creator) |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |
| deleted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Soft delete timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (category_id) REFERENCES lab_categories(id) ON DELETE SET NULL
- FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
- UNIQUE (name)

---

#### lab_flags
**Purpose:** Flags to be captured in labs.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| lab_id | INTEGER | NO | - | Foreign key to labs |
| flag_id | VARCHAR(100) | NO | - | Unique flag identifier within lab |
| name | VARCHAR(255) | NO | - | Flag name |
| description | TEXT | YES | NULL | Flag description |
| value | VARCHAR(255) | NO | - | Actual flag value (hashed in production) |
| points | INTEGER | NO | 100 | Points awarded |
| category | VARCHAR(50) | YES | NULL | Flag category (web, network, etc.) |
| hint | TEXT | YES | NULL | Optional hint |
| hint_penalty | INTEGER | NO | 10 | Points deducted for using hint |
| decay_window_seconds | INTEGER | NO | 1800 | Time decay window |
| sort_order | INTEGER | NO | 0 | Display order |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (lab_id) REFERENCES labs(id) ON DELETE CASCADE
- UNIQUE (lab_id, flag_id)

---

#### lab_objectives
**Purpose:** Learning objectives for labs.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| lab_id | INTEGER | NO | - | Foreign key to labs |
| title | VARCHAR(255) | NO | - | Objective title |
| description | TEXT | YES | NULL | Objective description |
| points | INTEGER | NO | 0 | Points awarded |
| sort_order | INTEGER | NO | 0 | Display order |
| is_required | BOOLEAN | NO | true | Required for completion |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (lab_id) REFERENCES labs(id) ON DELETE CASCADE

---

### 2.4 Module 4: Drill Management

#### drills
**Purpose:** Cyber drill exercise instances.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| title | VARCHAR(255) | NO | - | Drill title |
| description | TEXT | YES | NULL | Drill description |
| lab_id | INTEGER | YES | NULL | Foreign key to labs |
| status | drill_status | NO | 'scheduled' | Drill status |
| drill_type | VARCHAR(50) | NO | 'individual' | Type (individual, team, red_vs_blue) |
| scheduled_start_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Scheduled start time |
| scheduled_end_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Scheduled end time |
| actual_start_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Actual start time |
| actual_end_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Actual end time |
| duration_limit_minutes | INTEGER | YES | NULL | Time limit |
| max_participants | INTEGER | YES | NULL | Maximum participants |
| rules | JSONB | NO | '{}' | Drill-specific rules |
| environment_config | JSONB | NO | '{}' | VM/network configuration |
| created_by | INTEGER | YES | NULL | Foreign key to users (creator) |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |
| deleted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Soft delete timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (lab_id) REFERENCES labs(id) ON DELETE SET NULL
- FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL

---

#### drill_participants
**Purpose:** Track users participating in drills.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| drill_id | INTEGER | NO | - | Foreign key to drills |
| user_id | INTEGER | NO | - | Foreign key to users |
| team_id | INTEGER | YES | NULL | Foreign key to teams |
| role | VARCHAR(50) | NO | 'participant' | Participant role |
| status | VARCHAR(20) | NO | 'registered' | Participation status |
| joined_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Join time |
| completed_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Completion time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (drill_id) REFERENCES drills(id) ON DELETE CASCADE
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
- UNIQUE (drill_id, user_id)

---

### 2.5 Module 5: Submission System

#### submissions
**Purpose:** Parent table for all submission types.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| drill_id | INTEGER | YES | NULL | Foreign key to drills |
| lab_id | INTEGER | YES | NULL | Foreign key to labs |
| team_id | INTEGER | YES | NULL | Foreign key to teams |
| submission_type | VARCHAR(50) | NO | - | Type (flag, evidence, report) |
| status | submission_status | NO | 'pending' | Submission status |
| submitted_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Submission time |
| reviewed_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Review time |
| reviewed_by | INTEGER | YES | NULL | Foreign key to users (reviewer) |
| review_notes | TEXT | YES | NULL | Reviewer notes |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (drill_id) REFERENCES drills(id) ON DELETE CASCADE
- FOREIGN KEY (lab_id) REFERENCES labs(id) ON DELETE CASCADE
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
- FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL

---

#### flag_submissions
**Purpose:** Flag capture attempts.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| submission_id | INTEGER | NO | - | Foreign key to submissions |
| lab_flag_id | INTEGER | NO | - | Foreign key to lab_flags |
| flag_value | VARCHAR(255) | NO | - | Submitted flag value |
| is_correct | BOOLEAN | NO | false | Whether flag was correct |
| points_earned | INTEGER | NO | 0 | Points awarded |
| time_decay_factor | DECIMAL(3,2) | NO | 1.00 | Time decay multiplier |
| attempt_number | INTEGER | NO | 1 | Attempt sequence number |
| hints_used | INTEGER | NO | 0 | Number of hints used |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
- FOREIGN KEY (lab_flag_id) REFERENCES lab_flags(id) ON DELETE CASCADE
- UNIQUE (submission_id, lab_flag_id)

---

### 2.6 Module 6: Scoring System

#### scores
**Purpose:** Current scores for users/teams in drills.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| drill_id | INTEGER | YES | NULL | Foreign key to drills |
| team_id | INTEGER | YES | NULL | Foreign key to teams |
| total_points | INTEGER | NO | 0 | Total points |
| flags_captured | INTEGER | NO | 0 | Flags captured count |
| objectives_completed | INTEGER | NO | 0 | Objectives completed count |
| hints_used | INTEGER | NO | 0 | Hints used count |
| penalty_points | INTEGER | NO | 0 | Penalty points |
| time_bonus_points | INTEGER | NO | 0 | Time bonus points |
| first_blood_bonus | INTEGER | NO | 0 | First blood bonus |
| completion_time_seconds | INTEGER | YES | NULL | Completion time |
| rank_position | INTEGER | YES | NULL | Final rank |
| last_updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (drill_id) REFERENCES drills(id) ON DELETE CASCADE
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
- UNIQUE (user_id, drill_id)
- UNIQUE (team_id, drill_id)

---

### 2.7 Module 7: Benchmarking System

#### benchmarks
**Purpose:** Skill benchmark scores for users.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| overall_score | DECIMAL(5,2) | NO | 0 | Overall skill score |
| offensive_score | DECIMAL(5,2) | NO | 0 | Offensive skills |
| defensive_score | DECIMAL(5,2) | NO | 0 | Defensive skills |
| web_exploitation_score | DECIMAL(5,2) | NO | 0 | Web exploitation |
| network_exploitation_score | DECIMAL(5,2) | NO | 0 | Network exploitation |
| active_directory_score | DECIMAL(5,2) | NO | 0 | Active Directory |
| linux_score | DECIMAL(5,2) | NO | 0 | Linux skills |
| windows_score | DECIMAL(5,2) | NO | 0 | Windows skills |
| forensics_score | DECIMAL(5,2) | NO | 0 | Forensics skills |
| reporting_score | DECIMAL(5,2) | NO | 0 | Reporting skills |
| total_drills_completed | INTEGER | NO | 0 | Total drills completed |
| total_flags_captured | INTEGER | NO | 0 | Total flags captured |
| average_completion_time_seconds | INTEGER | YES | NULL | Average completion time |
| last_calculated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last calculation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- UNIQUE (user_id)

---

### 2.8 Module 8: Reporting System

#### reports
**Purpose:** After-action reports and assessments.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| drill_id | INTEGER | YES | NULL | Foreign key to drills |
| user_id | INTEGER | YES | NULL | Foreign key to users |
| team_id | INTEGER | YES | NULL | Foreign key to teams |
| title | VARCHAR(255) | NO | - | Report title |
| summary | TEXT | NO | - | Executive summary |
| content | TEXT | NO | - | Full report content |
| status | report_status | NO | 'draft' | Report status |
| report_type | VARCHAR(50) | NO | 'after_action' | Report type |
| quality_score | DECIMAL(5,2) | YES | NULL | Quality score |
| grade | VARCHAR(10) | YES | NULL | Letter grade |
| word_count | INTEGER | YES | NULL | Word count |
| file_path | VARCHAR(500) | YES | NULL | PDF export path |
| submitted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Submission time |
| graded_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Grading time |
| graded_by | INTEGER | YES | NULL | Foreign key to users (grader) |
| instructor_feedback | TEXT | YES | NULL | Instructor feedback |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (drill_id) REFERENCES drills(id) ON DELETE CASCADE
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
- FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL
- FOREIGN KEY (graded_by) REFERENCES users(id) ON DELETE SET NULL

---

#### report_findings
**Purpose:** Individual findings within reports.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| report_id | INTEGER | NO | - | Foreign key to reports |
| title | VARCHAR(255) | NO | - | Finding title |
| description | TEXT | NO | - | Finding description |
| severity | severity_level | NO | - | Severity level |
| category | VARCHAR(50) | YES | NULL | Finding category |
| evidence | TEXT | YES | NULL | Evidence description |
| impact | TEXT | YES | NULL | Impact assessment |
| recommendation | TEXT | YES | NULL | Remediation recommendation |
| cvss_score | DECIMAL(3,1) | YES | NULL | CVSS score (0.0-10.0) |
| cwe_id | VARCHAR(20) | YES | NULL | CWE identifier |
| sort_order | INTEGER | NO | 0 | Display order |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE

---

### 2.9 Module 9: Learning Path System

#### learning_paths
**Purpose:** Structured learning path definitions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| name | VARCHAR(255) | NO | - | Unique path identifier |
| title | VARCHAR(255) | NO | - | Human-readable title |
| description | TEXT | NO | - | Path description |
| difficulty | lab_difficulty | NO | 'beginner' | Difficulty level |
| estimated_duration_hours | INTEGER | YES | NULL | Estimated duration |
| is_public | BOOLEAN | NO | true | Public visibility |
| created_by | INTEGER | YES | NULL | Foreign key to users (creator) |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Creation time |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |
| deleted_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Soft delete timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
- UNIQUE (name)

---

#### user_learning_progress
**Purpose:** Track user progress through learning paths.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| user_id | INTEGER | NO | - | Foreign key to users |
| learning_path_id | INTEGER | NO | - | Foreign key to learning_paths |
| module_id | INTEGER | NO | - | Foreign key to learning_path_modules |
| lab_id | INTEGER | NO | - | Foreign key to labs |
| status | learning_path_status | NO | 'not_started' | Progress status |
| score | INTEGER | YES | NULL | Score achieved |
| completed_at | TIMESTAMP WITH TIME ZONE | YES | NULL | Completion time |
| started_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Start time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
- FOREIGN KEY (learning_path_id) REFERENCES learning_paths(id) ON DELETE CASCADE
- FOREIGN KEY (module_id) REFERENCES learning_path_modules(id) ON DELETE CASCADE
- FOREIGN KEY (lab_id) REFERENCES labs(id) ON DELETE CASCADE
- UNIQUE (user_id, learning_path_id, module_id, lab_id)

---

### 2.10 Module 10: Admin & Audit System

#### audit_logs
**Purpose:** Comprehensive audit trail for all system actions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| action | audit_action | NO | - | Action type enum |
| actor_id | INTEGER | YES | NULL | Foreign key to users (actor) |
| actor_username | VARCHAR(100) | YES | NULL | Actor username (denormalized) |
| resource_type | VARCHAR(50) | YES | NULL | Type of resource affected |
| resource_id | INTEGER | YES | NULL | ID of resource affected |
| ip_address | INET | YES | NULL | Client IP address |
| user_agent | TEXT | YES | NULL | Browser user agent |
| details | JSONB | NO | '{}' | Additional details |
| created_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Action timestamp |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL

---

#### platform_settings
**Purpose:** System-wide configuration settings.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| id | SERIAL | NO | auto | Primary key |
| setting_key | VARCHAR(100) | NO | - | Unique setting key |
| setting_value | JSONB | NO | - | Setting value (JSON) |
| description | TEXT | YES | NULL | Setting description |
| updated_by | INTEGER | YES | NULL | Foreign key to users (updater) |
| updated_at | TIMESTAMP WITH TIME ZONE | NO | NOW() | Last update time |

**Constraints:**
- PRIMARY KEY (id)
- FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
- UNIQUE (setting_key)


---

## 3. SQL Schema

The complete SQL schema is available in [`schema.sql`](schema.sql).

### Key Features:
- **PostgreSQL 15+ compatible**
- **50+ tables** across 10 modules
- **11 enum types** for type safety
- **Comprehensive indexing** for performance
- **Foreign key constraints** with appropriate CASCADE/SET NULL actions
- **Soft delete support** via `deleted_at` timestamps
- **Automatic `updated_at` triggers** for all relevant tables
- **Pre-built views** for common queries (leaderboard, active_drills, user_statistics)

### Schema Statistics:
- **Tables:** 50+
- **Indexes:** 100+
- **Foreign Keys:** 80+
- **Unique Constraints:** 25+
- **Enum Types:** 11
- **Views:** 3
- **Triggers:** 8

---

## 4. Example Data

### 4.1 Sample Users

```sql
-- Insert sample users
INSERT INTO users (sub, username, email, password_hash, role, is_active, email_verified) VALUES
('oauth|alice123', 'alice_hacker', 'alice@example.com', '$argon2id$v=19$m=65536,t=3,p=4$...', 'student', true, true),
('oauth|bob456', 'bob_sec', 'bob@example.com', '$argon2id$v=19$m=65536,t=3,p=4$...', 'student', true, true),
('oauth|charlie789', 'charlie_admin', 'charlie@example.com', '$argon2id$v=19$m=65536,t=3,p=4$...', 'administrator', true, true),
('oauth|diana012', 'diana_instructor', 'diana@example.com', '$argon2id$v=19$m=65536,t=3,p=4$...', 'instructor', true, true),
('oauth|eve345', 'eve_observer', 'eve@example.com', '$argon2id$v=19$m=65536,t=3,p=4$...', 'observer', true, true);

-- Insert user profiles
INSERT INTO user_profiles (user_id, full_name, bio, organization, skills, interests) VALUES
(1, 'Alice Johnson', 'Penetration tester specializing in web applications', 'CyberSec Corp', '["web", "networking", "linux"]', '["ctf", "reverse-engineering"]'),
(2, 'Bob Smith', 'Security analyst focused on defensive operations', 'SecureOps Inc', '["forensics", "siem", "incident-response"]', '["threat-hunting", "malware-analysis"]'),
(3, 'Charlie Brown', 'Platform administrator with 10+ years experience', 'OxBlood Platform', '["administration", "devops", "security"]', '["automation", "monitoring"]'),
(4, 'Diana Prince', 'Cybersecurity trainer and curriculum developer', 'Training Academy', '["teaching", "curriculum", "offensive-security"]', '["education", "mentoring"]'),
(5, 'Eve Wilson', 'Security auditor and compliance specialist', 'Audit Firm LLC', '["compliance", "auditing", "risk-assessment"]', '["governance", "policy"]');
```

### 4.2 Sample Roles and Permissions

```sql
-- Roles are defined via the user_role enum:
-- 'student', 'instructor', 'team_leader', 'administrator', 'observer'

-- Role hierarchy (implicit through permissions):
-- administrator > instructor > student
-- administrator > team_leader > student
-- observer (separate read-only track)
```

### 4.3 Sample Teams

```sql
-- Insert sample teams
INSERT INTO teams (name, description, organization, created_by, is_active) VALUES
('Red Team Alpha', 'Offensive security team specializing in penetration testing', 'CyberSec Corp', 3, true),
('Blue Team Beta', 'Defensive security team focused on incident response', 'SecureOps Inc', 3, true),
('Purple Team Gamma', 'Combined offensive and defensive operations', 'Training Academy', 3, true);

-- Insert team memberships
INSERT INTO team_memberships (team_id, user_id, role, is_active) VALUES
(1, 1, 'captain', true),  -- Alice captains Red Team
(1, 2, 'member', true),   -- Bob is member of Red Team
(2, 2, 'captain', true),  -- Bob also captains Blue Team
(3, 1, 'member', true),   -- Alice is member of Purple Team
(3, 2, 'member', true);   -- Bob is member of Purple Team
```

### 4.4 Sample Labs

```sql
-- Insert lab categories
INSERT INTO lab_categories (name, description, icon, sort_order) VALUES
('Web Exploitation', 'Web application security testing', '🌐', 1),
('Network Security', 'Network penetration testing', '🔌', 2),
('Cryptography', 'Cryptographic attacks and analysis', '🔐', 3),
('Forensics', 'Digital forensics and incident response', '🔍', 4),
('Active Directory', 'Windows domain attacks', '🏢', 5);

-- Insert tags
INSERT INTO tags (name, color) VALUES
('beginner', '#4ade80'),
('intermediate', '#facc15'),
('advanced', '#f87171'),
('web', '#3b82f6'),
('network', '#8b5cf6'),
('ctf', '#ec4899');

-- Insert sample lab
INSERT INTO labs (name, title, description, version, category_id, difficulty, duration_minutes, status, is_public, spec, authors, learning_objectives) VALUES
('sql-injection-basics', 'SQL Injection Basics', 'Learn the fundamentals of SQL injection attacks', 1, 1, 'beginner', 60, 'published', true, 
 '{"networks": [{"id": "default", "name": "Lab Network"}], "assets": [{"id": "web-server", "role": "target", "template": "tpl-ubuntu"}]}',
 '["Diana Prince"]',
 '["Understand SQL injection vulnerabilities", "Identify injection points", "Extract data using SQL injection"]');

-- Link lab to tags
INSERT INTO lab_tags (lab_id, tag_id) VALUES
(1, 1),  -- beginner
(1, 4);  -- web

-- Insert lab objectives
INSERT INTO lab_objectives (lab_id, title, description, points, sort_order, is_required) VALUES
(1, 'Identify SQL injection vulnerability', 'Find the vulnerable parameter in the login form', 50, 1, true),
(1, 'Extract database version', 'Use SQL injection to determine the database version', 75, 2, true),
(1, 'Dump user credentials', 'Extract usernames and password hashes from the users table', 100, 3, true);

-- Insert lab flags
INSERT INTO lab_flags (lab_id, flag_id, name, description, value, points, category, hint, hint_penalty, decay_window_seconds, sort_order) VALUES
(1, 'flag-1', 'Injection Point Flag', 'Flag for identifying the vulnerable parameter', 'FLAG{sql_injection_found}', 50, 'web', 'Try different input fields', 10, 1800, 1),
(1, 'flag-2', 'Database Version Flag', 'Flag for extracting database version', 'FLAG{postgres_15.2}', 75, 'web', 'Use UNION-based injection', 15, 1800, 2),
(1, 'flag-3', 'Credentials Flag', 'Flag for dumping user credentials', 'FLAG{admin:password123}', 100, 'web', 'Query the users table', 20, 1800, 3);
```

### 4.5 Sample Drills

```sql
-- Insert sample drill
INSERT INTO drills (title, description, lab_id, status, drill_type, scheduled_start_at, scheduled_end_at, duration_limit_minutes, max_participants, rules, environment_config, created_by) VALUES
('SQL Injection Challenge', 'Test your SQL injection skills in this timed challenge', 1, 'active', 'individual', 
 NOW(), NOW() + INTERVAL '2 hours', 120, 50,
 '{"allow_hints": true, "scoring": "time_decay"}',
 '{"vm_count": 1, "network_isolation": true}',
 4);  -- Created by Diana (instructor)

-- Insert drill participants
INSERT INTO drill_participants (drill_id, user_id, role, status) VALUES
(1, 1, 'participant', 'active'),  -- Alice participating
(1, 2, 'participant', 'active');  -- Bob participating
```

### 4.6 Sample Objectives and Flags

```sql
-- Insert drill objectives
INSERT INTO drill_objectives (drill_id, lab_objective_id, title, description, points, sort_order) VALUES
(1, 1, 'Find SQL injection', 'Identify the vulnerable parameter', 50, 1),
(1, 2, 'Extract DB version', 'Get database version info', 75, 2),
(1, 3, 'Dump credentials', 'Extract user credentials', 100, 3);
```

### 4.7 Sample Submissions

```sql
-- Insert submission (parent record)
INSERT INTO submissions (user_id, drill_id, lab_id, submission_type, status, submitted_at) VALUES
(1, 1, 1, 'flag', 'correct', NOW());

-- Insert flag submission
INSERT INTO flag_submissions (submission_id, lab_flag_id, flag_value, is_correct, points_earned, time_decay_factor, attempt_number, hints_used) VALUES
(1, 1, 'FLAG{sql_injection_found}', true, 50, 0.95, 1, 0);

-- Insert another submission for second flag
INSERT INTO submissions (user_id, drill_id, lab_id, submission_type, status, submitted_at) VALUES
(1, 1, 1, 'flag', 'correct', NOW() + INTERVAL '10 minutes');

INSERT INTO flag_submissions (submission_id, lab_flag_id, flag_value, is_correct, points_earned, time_decay_factor, attempt_number, hints_used) VALUES
(2, 2, 'FLAG{postgres_15.2}', true, 75, 0.85, 1, 1);  -- Used 1 hint
```

### 4.8 Sample Scores

```sql
-- Insert score for Alice
INSERT INTO scores (user_id, drill_id, total_points, flags_captured, objectives_completed, hints_used, penalty_points, time_bonus_points, first_blood_bonus, completion_time_seconds, rank_position) VALUES
(1, 1, 225, 3, 3, 1, 15, 50, 25, 1800, 1);

-- Insert score for Bob
INSERT INTO scores (user_id, drill_id, total_points, flags_captured, objectives_completed, hints_used, penalty_points, time_bonus_points, completion_time_seconds, rank_position) VALUES
(2, 1, 175, 2, 2, 2, 30, 0, 2400, 2);

-- Insert score history
INSERT INTO score_history (user_id, drill_id, action, points_change, previous_total, new_total, details) VALUES
(1, 1, 'flag_captured', 50, 0, 50, '{"flag_id": 1, "time_seconds": 300}'),
(1, 1, 'flag_captured', 75, 50, 125, '{"flag_id": 2, "time_seconds": 900, "hints_used": 1}'),
(1, 1, 'flag_captured', 100, 125, 225, '{"flag_id": 3, "time_seconds": 1800}');
```

### 4.9 Sample Reports

```sql
-- Insert report
INSERT INTO reports (drill_id, user_id, title, summary, content, status, report_type, quality_score, grade, word_count, submitted_at) VALUES
(1, 1, 'SQL Injection Challenge - After Action Report', 
 'Successfully completed all objectives in the SQL injection challenge.',
 '# Executive Summary\n\nCompleted all three objectives...',
 'graded', 'after_action', 85.5, 'A', 1500, NOW());

-- Insert report findings
INSERT INTO report_findings (report_id, title, description, severity, category, evidence, impact, recommendation, cvss_score, cwe_id, sort_order) VALUES
(1, 'SQL Injection Vulnerability', 'The login form is vulnerable to SQL injection attacks', 'high', 'vulnerability', 
 'Tested with single quote in username field', 'Attacker can bypass authentication and extract data',
 'Use parameterized queries and input validation', 8.5, 'CWE-89', 1),
(1, 'Information Disclosure', 'Database version information exposed', 'medium', 'misconfiguration',
 'Error messages reveal database type and version', 'Attackers can tailor attacks to specific database',
 'Suppress detailed error messages in production', 5.0, 'CWE-209', 2);
```


---

## 5. Database Design Explanation

### 5.1 Why the Schema is Structured This Way

The OxBlood database schema follows these design principles:

#### **Normalization (3NF)**
- Data is organized to minimize redundancy
- Each piece of information is stored in exactly one place
- Example: User information is in `users`, extended profile data in `user_profiles`

#### **Separation of Concerns**
- Each module handles a specific domain (users, teams, labs, drills, etc.)
- Clear boundaries between modules via foreign keys
- Independent evolution of each module

#### **Flexibility with JSONB**
- PostgreSQL JSONB columns store flexible, semi-structured data
- Used for: lab specifications, drill configurations, user preferences, audit details
- Allows schema evolution without migrations for certain features

#### **Soft Deletes**
- `deleted_at` timestamp instead of hard deletes
- Preserves historical data and relationships
- Enables audit trails and data recovery

#### **Audit Trail**
- Every table has `created_at` and `updated_at` timestamps
- Automatic triggers keep `updated_at` current
- Separate `audit_logs` table for detailed action tracking

#### **Performance Optimization**
- Strategic indexing on frequently queried columns
- Foreign keys indexed for join performance
- Composite indexes for common query patterns
- Views for complex, frequently-used queries

---

### 5.2 How Labs Connect to Drills

**Relationship Flow:**
```
labs (1) ──< drill_scenarios (N:M) >── drills (1)
```

**Explanation:**
1. **Labs** are reusable training scenarios (templates)
2. **Drills** are specific instances of exercises
3. **drill_scenarios** links drills to labs with optional overrides

**Example:**
```sql
-- Lab: "SQL Injection Basics" (reusable template)
-- Drill 1: "Monday Challenge" (uses SQL Injection lab)
-- Drill 2: "Wednesday Practice" (also uses SQL Injection lab)

INSERT INTO drill_scenarios (drill_id, lab_id, scenario_config) VALUES
(1, 1, '{"time_limit": 120, "difficulty": "easy"}'),
(2, 1, '{"time_limit": 60, "difficulty": "hard"}');
```

**Benefits:**
- Reuse lab content across multiple drills
- Customize difficulty, time limits, rules per drill
- Track which labs are used in which drills

---

### 5.3 How Users Connect to Teams

**Relationship Flow:**
```
users (N) ──< team_memberships (N:M) >── teams (N)
```

**Explanation:**
1. **users** can belong to multiple **teams**
2. **teams** can have multiple **users**
3. **team_memberships** is the join table with role information

**Example:**
```sql
-- Alice is captain of Red Team, member of Purple Team
-- Bob is captain of Blue Team, member of Red Team and Purple Team

INSERT INTO team_memberships (team_id, user_id, role) VALUES
(1, 1, 'captain'),  -- Alice captains Red Team
(1, 2, 'member'),   -- Bob is member of Red Team
(2, 2, 'captain'),  -- Bob captains Blue Team
(3, 1, 'member'),   -- Alice is member of Purple Team
(3, 2, 'member');   -- Bob is member of Purple Team
```

**Benefits:**
- Users can participate in multiple teams simultaneously
- Different roles per team (captain, member, coach)
- Track when users joined teams
- Support team invitations and requests

---

### 5.4 How Submissions Affect Scores

**Flow:**
```
User submits flag → submission created → flag_submissions created → scores updated → score_history recorded
```

**Detailed Process:**

1. **Submission Created:**
```sql
INSERT INTO submissions (user_id, drill_id, lab_id, submission_type, status)
VALUES (1, 1, 1, 'flag', 'pending');
```

2. **Flag Validated:**
```sql
INSERT INTO flag_submissions (submission_id, lab_flag_id, flag_value, is_correct, points_earned, time_decay_factor)
VALUES (1, 1, 'FLAG{sql_injection_found}', true, 50, 0.95);
```

3. **Score Updated:**
```sql
UPDATE scores 
SET total_points = total_points + 50,
    flags_captured = flags_captured + 1,
    last_updated_at = NOW()
WHERE user_id = 1 AND drill_id = 1;
```

4. **History Recorded:**
```sql
INSERT INTO score_history (user_id, drill_id, action, points_change, previous_total, new_total, details)
VALUES (1, 1, 'flag_captured', 50, 100, 150, '{"flag_id": 1}');
```

**Scoring Formula:**
```
Final Points = Base Points × Time Decay Factor - Hint Penalties + Bonuses

Where:
- Time Decay Factor = max(0.5, 1 - (elapsed_time / decay_window))
- Hint Penalties = hints_used × hint_penalty
- Bonuses = first_blood_bonus + time_bonus
```

---

### 5.5 How Benchmarking is Calculated

**Benchmark Calculation Process:**

1. **Collect Performance Data:**
   - Aggregate scores across all drills
   - Categorize by skill type (web, network, forensics, etc.)
   - Calculate averages and totals

2. **Calculate Category Scores:**
```sql
-- Example: Calculate web exploitation score
SELECT 
    user_id,
    AVG(s.total_points) as web_score
FROM scores s
JOIN drills d ON s.drill_id = d.id
JOIN labs l ON d.lab_id = l.id
JOIN lab_categories lc ON l.category_id = lc.id
WHERE lc.name = 'Web Exploitation'
GROUP BY user_id;
```

3. **Calculate Overall Score:**
```sql
overall_score = (
    offensive_score * 0.25 +
    defensive_score * 0.25 +
    web_exploitation_score * 0.10 +
    network_exploitation_score * 0.10 +
    active_directory_score * 0.10 +
    linux_score * 0.05 +
    windows_score * 0.05 +
    forensics_score * 0.05 +
    reporting_score * 0.05
)
```

4. **Store in benchmarks table:**
```sql
INSERT INTO benchmarks (user_id, overall_score, offensive_score, ...) VALUES
(1, 72.5, 85.0, 60.0, ...);
```

5. **Track History:**
```sql
INSERT INTO benchmark_history (user_id, drill_id, overall_score, ...) VALUES
(1, 1, 72.5, 85.0, 60.0, ...);
```

**Benefits:**
- Track skill progression over time
- Identify strengths and weaknesses
- Compare users across skill categories
- Generate personalized learning recommendations

---

### 5.6 How Reports are Linked to Drills and Users

**Relationship Flow:**
```
drills (1) ──< reports (N:1) >── users (1)
                  │
                  └──< report_findings (1:N)
                          │
                          └──< evidence (1:N)
```

**Explanation:**
1. **reports** are linked to a specific **drill** (optional)
2. **reports** are authored by a **user** (optional for team reports)
3. **reports** can be associated with a **team** (optional)
4. **report_findings** contain individual findings within the report
5. **evidence** supports each finding with artifacts

**Example:**
```sql
-- Alice submits a report for Drill 1
INSERT INTO reports (drill_id, user_id, team_id, title, summary, content, status) VALUES
(1, 1, NULL, 'SQL Injection Challenge Report', 'Successfully completed all objectives...', '# Full Report...', 'submitted');

-- Report contains multiple findings
INSERT INTO report_findings (report_id, title, description, severity, category) VALUES
(1, 'SQL Injection Vulnerability', 'Login form vulnerable to SQL injection', 'high', 'vulnerability'),
(1, 'Information Disclosure', 'Database version exposed in error messages', 'medium', 'misconfiguration');

-- Each finding has evidence
INSERT INTO evidence (finding_id, evidence_type, file_path, description) VALUES
(1, 'screenshot', '/evidence/sqli_proof.png', 'Screenshot of successful injection'),
(1, 'command_output', '/evidence/sqli_output.txt', 'Command output showing data extraction');
```

**Benefits:**
- Comprehensive after-action reporting
- Structured findings with severity levels
- Evidence attachment support
- Instructor feedback and grading
- CVSS scoring and CWE mapping

---

### 5.7 How Admin Audit Logs Track Platform Activity

**Audit Log Structure:**
```sql
audit_logs (
    id,
    action,           -- What happened (enum)
    actor_id,         -- Who did it
    actor_username,   -- Denormalized for performance
    resource_type,    -- What was affected
    resource_id,      -- ID of affected resource
    ip_address,       -- Where from
    user_agent,       -- Browser/client info
    details,          -- JSON with additional context
    created_at        -- When it happened
)
```

**Example Audit Entries:**

1. **User Login:**
```sql
INSERT INTO audit_logs (action, actor_id, actor_username, ip_address, details) VALUES
('user.login', 1, 'alice_hacker', '192.168.1.100', '{"session_id": "abc123"}');
```

2. **Lab Created:**
```sql
INSERT INTO audit_logs (action, actor_id, actor_username, resource_type, resource_id, details) VALUES
('lab.created', 4, 'diana_instructor', 'lab', 1, '{"name": "sql-injection-basics", "title": "SQL Injection Basics"}');
```

3. **Flag Captured:**
```sql
INSERT INTO audit_logs (action, actor_id, actor_username, resource_type, resource_id, details) VALUES
('flag.correct', 1, 'alice_hacker', 'flag', 1, '{"lab_id": 1, "points": 50, "time_seconds": 300}');
```

4. **Admin Action:**
```sql
INSERT INTO audit_logs (action, actor_id, actor_username, resource_type, resource_id, details) VALUES
('admin.action', 3, 'charlie_admin', 'user', 2, '{"action": "role_change", "old_role": "student", "new_role": "instructor"}');
```

**Benefits:**
- Complete audit trail for compliance
- Security incident investigation
- User behavior analysis
- Debugging and troubleshooting
- Accountability and transparency

**Query Examples:**
```sql
-- Get all actions by a user
SELECT * FROM audit_logs WHERE actor_id = 1 ORDER BY created_at DESC;

-- Get all actions on a specific resource
SELECT * FROM audit_logs WHERE resource_type = 'lab' AND resource_id = 1;

-- Get all admin actions
SELECT * FROM audit_logs WHERE action LIKE 'admin.%';

-- Get failed login attempts
SELECT * FROM audit_logs WHERE action = 'user.login_failed' AND created_at > NOW() - INTERVAL '1 hour';
```


---

## 6. Security Considerations

### 6.1 Password Hashing

**Implementation:**
- Use **Argon2id** algorithm (winner of Password Hashing Competition)
- Parameters: memory=65536 KB, iterations=3, parallelism=4
- Store only the hash in `users.password_hash`
- Never store plaintext passwords

**SQL Example:**
```sql
-- Password hash format (generated by application)
UPDATE users SET password_hash = '$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$...' WHERE id = 1;
```

**Best Practices:**
- Minimum 128-bit salt (automatically included in Argon2)
- Regularly rehash passwords with updated parameters
- Enforce strong password policies (length, complexity)
- Implement rate limiting on login attempts

---

### 6.2 Role-Based Access Control (RBAC)

**Implementation:**
- Use `user_role` enum: `student`, `instructor`, `team_leader`, `administrator`, `observer`
- Enforce permissions at application layer
- Use database-level constraints for critical operations

**Permission Matrix:**

| Action | Student | Instructor | Team Leader | Administrator | Observer |
|--------|---------|------------|-------------|---------------|----------|
| View own data | ✅ | ✅ | ✅ | ✅ | ✅ |
| Submit flags | ✅ | ✅ | ✅ | ❌ | ❌ |
| Create labs | ❌ | ✅ | ❌ | ✅ | ❌ |
| Manage users | ❌ | ❌ | ❌ | ✅ | ❌ |
| View all reports | ❌ | ✅ (scoped) | ❌ | ✅ | ✅ |
| View audit logs | ❌ | ❌ | ❌ | ✅ | ✅ |

**Database Enforcement:**
```sql
-- Example: Trigger to prevent non-admins from changing roles
CREATE OR REPLACE FUNCTION check_role_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Only administrators can change user roles
    IF OLD.role != NEW.role THEN
        IF NOT EXISTS (
            SELECT 1 FROM users WHERE id = current_setting('app.current_user_id')::int AND role = 'administrator'
        ) THEN
            RAISE EXCEPTION 'Only administrators can change user roles';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_role_changes
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION check_role_change();
```

---

### 6.3 Audit Logging

**Implementation:**
- Log all security-relevant actions in `audit_logs`
- Include: who, what, when, where (IP), and details
- Use triggers for automatic logging on critical tables
- Retain logs for compliance (minimum 1 year recommended)

**Automatic Audit Trigger Example:**
```sql
-- Function to log user changes
CREATE OR REPLACE FUNCTION log_user_changes()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_logs (action, actor_id, resource_type, resource_id, details)
    VALUES (
        'user.updated',
        current_setting('app.current_user_id')::int,
        'user',
        NEW.id,
        jsonb_build_object(
            'changes', jsonb_build_object(
                'role', jsonb_build_object('old', OLD.role, 'new', NEW.role),
                'is_active', jsonb_build_object('old', OLD.is_active, 'new', NEW.is_active)
            )
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_user_updates
    AFTER UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION log_user_changes();
```

**Security Events:**
- Track failed login attempts in `security_events`
- Alert on brute force patterns (5+ failures in 5 minutes)
- Monitor suspicious activity (unusual access patterns)
- Log privilege escalation attempts

---

### 6.4 Sensitive Data Protection

**Protected Fields:**
- `users.password_hash` - Never expose in API responses
- `users.email` - Mask in public views (alice@***.com)
- `sessions.session_token` - Secure, http-only cookies
- `lab_flags.value` - Hash in production, never expose in logs

**Encryption at Rest:**
```sql
-- Enable PostgreSQL TDE (Transparent Data Encryption)
-- Or use pgcrypto for specific columns

-- Example: Encrypt sensitive field
UPDATE users SET 
    email = pgp_sym_encrypt('alice@example.com', current_setting('app.encryption_key'))
WHERE id = 1;

-- Decrypt when needed
SELECT pgp_sym_decrypt(email::bytea, current_setting('app.encryption_key')) FROM users WHERE id = 1;
```

**Data Masking:**
```sql
-- Create view with masked emails
CREATE VIEW public_users AS
SELECT 
    id,
    username,
    CONCAT(LEFT(email, 2), '***@', SPLIT_PART(email, '@', 2)) AS masked_email,
    role,
    created_at
FROM users
WHERE is_active = true AND deleted_at IS NULL;
```

---

### 6.5 Secure Flag Storage

**Implementation:**
- Store flag values as **SHA-256 hashes** in production
- Use unique salt per lab
- Never log flag values
- Validate submissions against hashed values

**Example:**
```sql
-- During lab creation (application layer)
flag_value = "FLAG{sql_injection_found}"
flag_hash = sha256(flag_value + lab_salt)

-- Store hash in database
INSERT INTO lab_flags (lab_id, flag_id, name, value, points) VALUES
(1, 'flag-1', 'SQL Injection Flag', 'sha256:abc123...', 50);

-- During submission validation (application layer)
submitted_hash = sha256(submitted_value + lab_salt)
IF submitted_hash == stored_hash THEN
    -- Flag is correct
END IF;
```

**Benefits:**
- Flags cannot be extracted from database dumps
- Compromised database doesn't reveal flag values
- Each lab uses unique salt (prevents rainbow table attacks)

---

### 6.6 Input Validation

**Database-Level Validation:**
```sql
-- Email format validation
ALTER TABLE users ADD CONSTRAINT chk_email_format 
    CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$');

-- Username length and character validation
ALTER TABLE users ADD CONSTRAINT chk_username_format 
    CHECK (username ~ '^[a-zA-Z0-9_-]{3,50}$');

-- Score range validation
ALTER TABLE scores ADD CONSTRAINT chk_total_points 
    CHECK (total_points >= 0);

-- CVSS score range (0.0-10.0)
ALTER TABLE report_findings ADD CONSTRAINT chk_cvss_range 
    CHECK (cvss_score IS NULL OR (cvss_score >= 0.0 AND cvss_score <= 10.0));
```

**Application-Level Validation:**
- Validate all inputs before database insertion
- Use parameterized queries (prevent SQL injection)
- Sanitize user inputs (prevent XSS)
- Validate file uploads (size, type, content)

---

### 6.7 Rate Limiting Support

**Implementation:**
- Track submission attempts in `submission_attempts`
- Implement application-level rate limiting (Redis)
- Use database constraints to prevent abuse

**Example:**
```sql
-- Prevent duplicate flag submissions (same user, same flag, same attempt number)
ALTER TABLE submission_attempts ADD CONSTRAINT uq_submission_attempts 
    UNIQUE (user_id, lab_flag_id, attempt_number);

-- Query to check rate limit (last 5 minutes)
SELECT COUNT(*) as recent_attempts
FROM submission_attempts
WHERE user_id = 1 
  AND submitted_at > NOW() - INTERVAL '5 minutes';
```

**Rate Limit Rules:**
- Max 10 flag submissions per minute per user
- Max 50 flag submissions per hour per user
- Exponential backoff after repeated failures
- Temporary lockout after 10 failed attempts

---

### 6.8 Preventing Duplicate Flag Submissions

**Implementation:**
```sql
-- Unique constraint prevents same user submitting same flag twice
ALTER TABLE flag_submissions ADD CONSTRAINT uq_flag_submissions 
    UNIQUE (submission_id, lab_flag_id);

-- Check before insertion (application layer)
SELECT EXISTS (
    SELECT 1 FROM flag_submissions fs
    JOIN submissions s ON fs.submission_id = s.id
    WHERE s.user_id = 1 
      AND fs.lab_flag_id = 1 
      AND fs.is_correct = true
) as already_captured;
```

**Benefits:**
- Prevents point farming
- Ensures fair scoring
- Maintains data integrity

---

### 6.9 Permission Separation

**Student vs Instructor vs Admin:**

**Students:**
- Can only see their own submissions, scores, and reports
- Cannot view other users' data
- Cannot modify labs or drills

**Instructors:**
- Can view data for students in their assigned drills
- Can create and modify labs
- Can grade reports for their students
- Cannot modify platform settings

**Administrators:**
- Full access to all data
- Can manage users, roles, and permissions
- Can modify platform settings
- Can view audit logs

**Implementation Example:**
```sql
-- View for students (only their own data)
CREATE VIEW student_scores AS
SELECT s.*
FROM scores s
WHERE s.user_id = current_setting('app.current_user_id')::int;

-- View for instructors (their students' data)
CREATE VIEW instructor_scores AS
SELECT s.*
FROM scores s
JOIN drill_participants dp ON s.user_id = dp.user_id
JOIN drills d ON dp.drill_id = d.id
WHERE d.created_by = current_setting('app.current_user_id')::int;

-- Administrators see everything (no view restriction)
```

**Row-Level Security (RLS):**
```sql
-- Enable RLS on sensitive tables
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;

-- Policy: Students can only see their own scores
CREATE POLICY student_scores_policy ON scores
    FOR SELECT
    USING (user_id = current_setting('app.current_user_id')::int);

-- Policy: Instructors can see scores for their drills
CREATE POLICY instructor_scores_policy ON scores
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM drills d
            JOIN drill_participants dp ON d.id = dp.drill_id
            WHERE d.id = scores.drill_id
              AND d.created_by = current_setting('app.current_user_id')::int
              AND dp.user_id = scores.user_id
        )
    );

-- Policy: Administrators can see all scores
CREATE POLICY admin_scores_policy ON scores
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM users 
            WHERE id = current_setting('app.current_user_id')::int 
              AND role = 'administrator'
        )
    );
```


---

## 7. Future Scalability

### 7.1 Multi-Organization Support

**Current State:**
- Single-tenant architecture
- All users in one database
- No organization isolation

**Future Enhancement:**
```sql
-- Add organization_id to all major tables
ALTER TABLE users ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
ALTER TABLE teams ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
ALTER TABLE labs ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
ALTER TABLE drills ADD COLUMN organization_id INTEGER REFERENCES organizations(id);

-- Create organizations table
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    domain VARCHAR(255),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Enable Row-Level Security for multi-tenancy
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation ON users
    FOR ALL
    USING (organization_id = current_setting('app.current_org_id')::int);
```

**Benefits:**
- SaaS deployment model
- Data isolation between organizations
- Organization-specific branding and settings
- Shared infrastructure, isolated data

---

### 7.2 Event-Based Scoring Engine

**Current State:**
- Synchronous score updates
- Direct database updates on flag submission
- Limited extensibility

**Future Enhancement:**
```sql
-- Event log for scoring engine
CREATE TABLE scoring_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL, -- flag_submitted, hint_used, objective_completed
    user_id INTEGER REFERENCES users(id),
    drill_id INTEGER REFERENCES drills(id),
    team_id INTEGER REFERENCES teams(id),
    payload JSONB NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Scoring rules engine
CREATE TABLE scoring_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    conditions JSONB NOT NULL, -- When to apply rule
    actions JSONB NOT NULL, -- What to do (add points, apply penalty, etc.)
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Example rule: First blood bonus
INSERT INTO scoring_rules (name, event_type, conditions, actions, priority) VALUES
('first_blood_bonus', 'flag_submitted', 
 '{"is_first": true}', 
 '{"action": "add_points", "amount": 50}', 
 100);
```

**Benefits:**
- Decoupled scoring logic
- Configurable scoring rules per drill
- Event sourcing for audit trail
- Easy to add new scoring mechanisms
- Replay events for debugging

---

### 7.3 Lab Container Orchestration

**Current State:**
- Proxmox VE for VM management
- Manual template creation
- Limited automation

**Future Enhancement:**
```sql
-- Container orchestration metadata
CREATE TABLE lab_environments (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER REFERENCES labs(id),
    orchestrator VARCHAR(50) NOT NULL, -- proxmox, kubernetes, docker
    config JSONB NOT NULL, -- Orchestrator-specific config
    status VARCHAR(20) NOT NULL, -- pending, provisioning, ready, failed, destroyed
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    destroyed_at TIMESTAMP WITH TIME ZONE
);

-- Container definitions
CREATE TABLE lab_containers (
    id SERIAL PRIMARY KEY,
    environment_id INTEGER REFERENCES lab_environments(id),
    name VARCHAR(100) NOT NULL,
    image VARCHAR(255) NOT NULL,
    resources JSONB NOT NULL, -- CPU, memory, disk
    network_config JSONB,
    volumes JSONB,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Network topology
CREATE TABLE lab_networks (
    id SERIAL PRIMARY KEY,
    environment_id INTEGER REFERENCES lab_environments(id),
    name VARCHAR(100) NOT NULL,
    cidr VARCHAR(18) NOT NULL,
    vlan_id INTEGER,
    isolation_level VARCHAR(20), -- isolated, nat, bridged
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

**Benefits:**
- Support multiple orchestrators (Proxmox, Kubernetes, Docker)
- Faster lab provisioning (containers vs VMs)
- Better resource utilization
- Easier to scale horizontally
- Support for ephemeral environments

---

### 7.4 Real-Time Scoreboard

**Current State:**
- Polling-based updates
- Database queries for leaderboard
- Limited real-time capabilities

**Future Enhancement:**
```sql
-- Materialized view for real-time leaderboard
CREATE MATERIALIZED VIEW realtime_leaderboard AS
SELECT 
    u.id AS user_id,
    u.username,
    u.organization_id,
    COALESCE(SUM(s.total_points), 0) AS total_points,
    COALESCE(SUM(s.flags_captured), 0) AS total_flags,
    COUNT(DISTINCT s.drill_id) AS drills_completed,
    RANK() OVER (ORDER BY COALESCE(SUM(s.total_points), 0) DESC) AS rank
FROM users u
LEFT JOIN scores s ON u.id = s.user_id
WHERE u.is_active = true AND u.deleted_at IS NULL
GROUP BY u.id, u.username, u.organization_id;

-- Refresh every 30 seconds
CREATE OR REPLACE FUNCTION refresh_leaderboard()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY realtime_leaderboard;
END;
$$ LANGUAGE plpgsql;

-- Use pg_cron or application scheduler
-- SELECT cron.schedule('refresh-leaderboard', '30 seconds', 'SELECT refresh_leaderboard()');
```

**WebSocket Integration:**
```sql
-- Track active connections
CREATE TABLE websocket_connections (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    channel VARCHAR(50) NOT NULL, -- leaderboard, drill_updates, notifications
    connected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_ping_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Publish events to Redis pub/sub (application layer)
-- Redis channel: "oxblood:leaderboard:update"
-- Payload: {"user_id": 1, "new_rank": 5, "points": 1250}
```

**Benefits:**
- Sub-second leaderboard updates
- Reduced database load (materialized views)
- Real-time notifications via WebSockets
- Better user experience during live drills

---

### 7.5 SIEM Integration

**Current State:**
- Basic audit logging
- No correlation with external SIEM
- Limited security monitoring

**Future Enhancement:**
```sql
-- SIEM event export queue
CREATE TABLE siem_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    source VARCHAR(50) NOT NULL, -- oxblood, wazuh, proxmox
    payload JSONB NOT NULL,
    exported_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- SIEM configuration
CREATE TABLE siem_integrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL, -- syslog, http, splunk, elasticsearch
    endpoint VARCHAR(500) NOT NULL,
    credentials JSONB, -- Encrypted
    enabled BOOLEAN NOT NULL DEFAULT true,
    last_test_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Correlation rules
CREATE TABLE siem_correlation_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    conditions JSONB NOT NULL, -- Event patterns to match
    actions JSONB NOT NULL, -- Alert, block, notify
    severity VARCHAR(20) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

**Integration Points:**
- **Wazuh**: Forward security events via syslog
- **Splunk**: HTTP Event Collector (HEC) integration
- **Elasticsearch**: Bulk API for log ingestion
- **Custom Webhooks**: HTTP POST for generic SIEMs

**Benefits:**
- Centralized security monitoring
- Correlation across multiple data sources
- Automated incident response
- Compliance reporting (SOC 2, ISO 27001)
- Threat detection and alerting

---

### 7.6 API Token System

**Current State:**
- JWT-based authentication only
- No long-lived API tokens
- Limited automation support

**Future Enhancement:**
```sql
-- API tokens for automation
CREATE TABLE api_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    token_hash VARCHAR(255) NOT NULL, -- SHA-256 hash of token
    permissions JSONB NOT NULL DEFAULT '[]', -- Array of permission strings
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Token usage logs
CREATE TABLE api_token_usage (
    id SERIAL PRIMARY KEY,
    token_id INTEGER REFERENCES api_tokens(id) ON DELETE CASCADE,
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    ip_address INET,
    response_code INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Example: Create token for CI/CD integration
INSERT INTO api_tokens (user_id, name, token_hash, permissions, expires_at) VALUES
(3, 'CI/CD Pipeline', 'sha256:abc123...', '["drill:create", "drill:start", "lab:read"]', NOW() + INTERVAL '1 year');
```

**Benefits:**
- Automation and CI/CD integration
- Granular permission control
- Token rotation and expiration
- Audit trail for API usage
- Revoke tokens without affecting user sessions

**Use Cases:**
- Automated drill scheduling
- External tool integration (Jenkins, GitLab CI)
- Third-party dashboard integration
- Bulk data import/export

---

### 7.7 Plugin-Based Lab Categories

**Current State:**
- Fixed lab categories
- Hardcoded scoring logic
- Limited extensibility

**Future Enhancement:**
```sql
-- Plugin registry
CREATE TABLE lab_plugins (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    version VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL, -- web, network, crypto, forensics, custom
    entry_point VARCHAR(255) NOT NULL, -- Python module path
    config_schema JSONB, -- JSON Schema for plugin config
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Plugin configurations per lab
CREATE TABLE lab_plugin_configs (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER REFERENCES labs(id) ON DELETE CASCADE,
    plugin_id INTEGER REFERENCES lab_plugins(id) ON DELETE CASCADE,
    config JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lab_plugin UNIQUE (lab_id, plugin_id)
);

-- Example: Custom CTF plugin
INSERT INTO lab_plugins (name, version, category, entry_point, config_schema) VALUES
('jeopardy_ctf', '1.0.0', 'ctf', 'oxblood.plugins.jeopardy_ctf', 
 '{"type": "object", "properties": {"max_attempts": {"type": "integer"}}}');

-- Configure plugin for a lab
INSERT INTO lab_plugin_configs (lab_id, plugin_id, config) VALUES
(1, 1, '{"max_attempts": 10, "hint_system": true}');
```

**Plugin Types:**
- **Scoring Plugins**: Custom scoring algorithms
- **Validation Plugins**: Custom flag validation logic
- **Environment Plugins**: Custom lab provisioning
- **Reporting Plugins**: Custom report generation
- **Integration Plugins**: Third-party service integration

**Benefits:**
- Extensible without code changes
- Community-contributed plugins
- Custom lab types (CTF, red team, blue team, etc.)
- Flexible scoring mechanisms
- Easy to add new features

**Example Plugins:**
- `jeopardy_ctf`: Standard CTF scoring
- `king_of_hill`: Competitive capture-the-flag
- `attack_defense`: Red vs blue team scoring
- `scenario_based`: Narrative-driven exercises
- `skill_assessment`: Competency-based evaluation

---

## Summary

The OxBlood database schema provides a **comprehensive, production-ready foundation** for a modern cybersecurity training platform. Key highlights:

### ✅ What We've Built

1. **50+ Tables** covering all 10 modules
2. **Robust Relationships** with proper foreign keys and constraints
3. **Performance Optimized** with strategic indexing
4. **Security First** with RBAC, audit logging, and data protection
5. **Scalable Architecture** ready for future enhancements
6. **Well Documented** with ER diagrams, examples, and explanations

### 🎯 Key Features

- **User Management**: Complete authentication, profiles, badges
- **Team Collaboration**: Teams, memberships, invitations
- **Lab System**: Reusable scenarios with flags, hints, objectives
- **Drill Engine**: Flexible exercise management
- **Submission System**: Flag captures, evidence, reports
- **Scoring Engine**: Time-decay, penalties, bonuses, rankings
- **Benchmarking**: Skill tracking across 9 categories
- **Reporting**: Structured findings with evidence
- **Learning Paths**: Guided skill progression
- **Audit & Admin**: Complete audit trail and monitoring

### 🚀 Ready for Production

- PostgreSQL 15+ compatible
- Comprehensive SQL schema provided
- Sample data for testing
- Security best practices implemented
- Scalability considerations documented

### 📚 Documentation Provided

1. **Entity Relationship Design** - Complete ER diagram and relationships
2. **Database Tables** - Detailed table specifications
3. **SQL Schema** - Ready-to-deploy PostgreSQL schema
4. **Example Data** - Sample inserts for testing
5. **Design Explanation** - Why and how the schema works
6. **Security Considerations** - Comprehensive security guide
7. **Future Scalability** - Roadmap for enhancements

---
## 12. Deployable SQL Schema (full, verbatim)

> Source: former `docs/schema.sql` (973 lines, PostgreSQL 15+). Deploy with `psql -U postgres -d oxblood -f schema.sql` (copy kept at repo root `schema.sql` too).

```sql
-- OxBlood Database Schema
-- PostgreSQL 15+
-- Comprehensive schema for cybersecurity training platform

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

CREATE TYPE user_role AS ENUM ('student', 'instructor', 'team_leader', 'administrator', 'observer');
CREATE TYPE lab_status AS ENUM ('draft', 'published', 'archived');
CREATE TYPE lab_difficulty AS ENUM ('beginner', 'easy', 'medium', 'hard', 'expert');
CREATE TYPE drill_status AS ENUM ('scheduled', 'active', 'paused', 'completed', 'cancelled');
CREATE TYPE submission_status AS ENUM ('pending', 'correct', 'incorrect', 'partial', 'reviewed');
CREATE TYPE report_status AS ENUM ('draft', 'submitted', 'under_review', 'graded', 'approved');
CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'informational');
CREATE TYPE evidence_type AS ENUM ('screenshot', 'command_output', 'log_excerpt', 'network_capture', 'file', 'other');
CREATE TYPE audit_action AS ENUM ('user.created', 'user.updated', 'user.deleted', 'user.login', 'user.logout', 'lab.created', 'lab.updated', 'lab.published', 'lab.archived', 'drill.created', 'drill.started', 'drill.completed', 'flag.submitted', 'flag.correct', 'flag.incorrect', 'report.created', 'report.submitted', 'report.graded', 'team.created', 'team.updated', 'team.member_added', 'team.member_removed', 'score.updated', 'benchmark.calculated', 'admin.action');
CREATE TYPE notification_type AS ENUM ('info', 'warning', 'error', 'success', 'achievement', 'deadline');
CREATE TYPE learning_path_status AS ENUM ('not_started', 'in_progress', 'completed');

-- ============================================================================
-- MODULE 1: USER MANAGEMENT
-- ============================================================================

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    sub VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    role user_role NOT NULL DEFAULT 'student',
    is_active BOOLEAN NOT NULL DEFAULT true,
    email_verified BOOLEAN NOT NULL DEFAULT false,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT chk_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$')
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_active ON users(is_active) WHERE deleted_at IS NULL;

CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255),
    bio TEXT,
    avatar_url VARCHAR(500),
    organization VARCHAR(255),
    location VARCHAR(255),
    website VARCHAR(500),
    github_username VARCHAR(100),
    linkedin_url VARCHAR(500),
    skills JSONB DEFAULT '[]',
    interests JSONB DEFAULT '[]',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_profiles_user UNIQUE (user_id)
);

CREATE INDEX idx_user_profiles_user ON user_profiles(user_id);

CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    ip_address INET,
    user_agent TEXT,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

CREATE TABLE password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_password_reset_user ON password_reset_tokens(user_id);
CREATE INDEX idx_password_reset_token ON password_reset_tokens(token);
CREATE INDEX idx_password_reset_expires ON password_reset_tokens(expires_at);

CREATE TABLE user_activity_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id INTEGER,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_activity_user ON user_activity_logs(user_id);
CREATE INDEX idx_user_activity_action ON user_activity_logs(action);
CREATE INDEX idx_user_activity_created ON user_activity_logs(created_at);

CREATE TABLE badges (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT NOT NULL,
    icon VARCHAR(50) NOT NULL,
    criteria JSONB NOT NULL,
    category VARCHAR(50) NOT NULL,
    rarity VARCHAR(20) NOT NULL DEFAULT 'common',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE user_badges (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_id INTEGER NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
    earned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_badges UNIQUE (user_id, badge_id)
);

CREATE INDEX idx_user_badges_user ON user_badges(user_id);
CREATE INDEX idx_user_badges_badge ON user_badges(badge_id);

-- ============================================================================
-- MODULE 2: TEAM MANAGEMENT
-- ============================================================================

CREATE TABLE teams (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    organization VARCHAR(255),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_teams_name ON teams(name);
CREATE INDEX idx_teams_active ON teams(is_active) WHERE deleted_at IS NULL;

CREATE TABLE team_memberships (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_team_memberships UNIQUE (team_id, user_id)
);

CREATE INDEX idx_team_memberships_team ON team_memberships(team_id);
CREATE INDEX idx_team_memberships_user ON team_memberships(user_id);

CREATE TABLE team_invitations (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invited_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(255),
    token VARCHAR(255) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    responded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_team_invitations_team ON team_invitations(team_id);
CREATE INDEX idx_team_invitations_user ON team_invitations(invited_user_id);
CREATE INDEX idx_team_invitations_token ON team_invitations(token);
CREATE INDEX idx_team_invitations_status ON team_invitations(status);

CREATE TABLE team_statistics (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    drill_id INTEGER,
    total_score INTEGER NOT NULL DEFAULT 0,
    flags_captured INTEGER NOT NULL DEFAULT 0,
    objectives_completed INTEGER NOT NULL DEFAULT 0,
    average_time_seconds INTEGER,
    rank_position INTEGER,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_team_statistics_team ON team_statistics(team_id);
CREATE INDEX idx_team_statistics_drill ON team_statistics(drill_id);

-- ============================================================================
-- MODULE 3: LAB MANAGEMENT
-- ============================================================================

CREATE TABLE lab_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    icon VARCHAR(50),
    parent_id INTEGER REFERENCES lab_categories(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_categories_parent ON lab_categories(parent_id);

CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    color VARCHAR(7),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE labs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER REFERENCES lab_categories(id) ON DELETE SET NULL,
    difficulty lab_difficulty NOT NULL DEFAULT 'beginner',
    duration_minutes INTEGER,
    status lab_status NOT NULL DEFAULT 'draft',
    is_public BOOLEAN NOT NULL DEFAULT false,
    requires_team BOOLEAN NOT NULL DEFAULT false,
    min_team_size INTEGER,
    max_team_size INTEGER,
    spec JSONB NOT NULL DEFAULT '{}',
    authors JSONB DEFAULT '[]',
    prerequisites JSONB DEFAULT '[]',
    learning_objectives JSONB DEFAULT '[]',
    source_path VARCHAR(500),
    published_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_labs_name ON labs(name);
CREATE INDEX idx_labs_category ON labs(category_id);
CREATE INDEX idx_labs_difficulty ON labs(difficulty);
CREATE INDEX idx_labs_status ON labs(status);
CREATE INDEX idx_labs_public ON labs(is_public);

CREATE TABLE lab_tags (
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lab_id, tag_id)
);

CREATE INDEX idx_lab_tags_lab ON lab_tags(lab_id);
CREATE INDEX idx_lab_tags_tag ON lab_tags(tag_id);

CREATE TABLE target_machines (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,
    os_type VARCHAR(50) NOT NULL,
    os_version VARCHAR(50),
    ip_address INET,
    template_name VARCHAR(100),
    vulnerabilities JSONB DEFAULT '[]',
    services JSONB DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_target_machines_lab ON target_machines(lab_id);

CREATE TABLE lab_objectives (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_required BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_objectives_lab ON lab_objectives(lab_id);

CREATE TABLE lab_flags (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    flag_id VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    value VARCHAR(255) NOT NULL,
    points INTEGER NOT NULL DEFAULT 100,
    category VARCHAR(50),
    hint TEXT,
    hint_penalty INTEGER NOT NULL DEFAULT 10,
    decay_window_seconds INTEGER NOT NULL DEFAULT 1800,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lab_flags UNIQUE (lab_id, flag_id)
);

CREATE INDEX idx_lab_flags_lab ON lab_flags(lab_id);

CREATE TABLE lab_hints (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    penalty_points INTEGER NOT NULL DEFAULT 5,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_hints_lab ON lab_hints(lab_id);
CREATE INDEX idx_lab_hints_objective ON lab_hints(objective_id);

CREATE TABLE lab_files (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    is_downloadable BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_files_lab ON lab_files(lab_id);

-- ============================================================================
-- MODULE 4: CYBER DRILL MANAGEMENT
-- ============================================================================

CREATE TABLE drills (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    lab_id INTEGER REFERENCES labs(id) ON DELETE SET NULL,
    status drill_status NOT NULL DEFAULT 'scheduled',
    drill_type VARCHAR(50) NOT NULL DEFAULT 'individual',
    scheduled_start_at TIMESTAMP WITH TIME ZONE,
    scheduled_end_at TIMESTAMP WITH TIME ZONE,
    actual_start_at TIMESTAMP WITH TIME ZONE,
    actual_end_at TIMESTAMP WITH TIME ZONE,
    duration_limit_minutes INTEGER,
    max_participants INTEGER,
    rules JSONB DEFAULT '{}',
    environment_config JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_drills_status ON drills(status);
CREATE INDEX idx_drills_lab ON drills(lab_id);
CREATE INDEX idx_drills_scheduled ON drills(scheduled_start_at);

CREATE TABLE drill_scenarios (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    scenario_config JSONB DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_drill_scenarios UNIQUE (drill_id, lab_id)
);

CREATE INDEX idx_drill_scenarios_drill ON drill_scenarios(drill_id);
CREATE INDEX idx_drill_scenarios_lab ON drill_scenarios(lab_id);

CREATE TABLE drill_participants (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'participant',
    status VARCHAR(20) NOT NULL DEFAULT 'registered',
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_drill_participants UNIQUE (drill_id, user_id)
);

CREATE INDEX idx_drill_participants_drill ON drill_participants(drill_id);
CREATE INDEX idx_drill_participants_user ON drill_participants(user_id);
CREATE INDEX idx_drill_participants_team ON drill_participants(team_id);

CREATE TABLE drill_teams (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    team_side VARCHAR(20),
    registered_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_drill_teams UNIQUE (drill_id, team_id)
);

CREATE INDEX idx_drill_teams_drill ON drill_teams(drill_id);
CREATE INDEX idx_drill_teams_team ON drill_teams(team_id);

CREATE TABLE drill_objectives (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    points INTEGER NOT NULL DEFAULT 0,
    side VARCHAR(20),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drill_objectives_drill ON drill_objectives(drill_id);

CREATE TABLE drill_announcements (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    published_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drill_announcements_drill ON drill_announcements(drill_id);
CREATE INDEX idx_drill_announcements_published ON drill_announcements(published_at);

-- ============================================================================
-- MODULE 5: SUBMISSION SYSTEM
-- ============================================================================

CREATE TABLE submissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER REFERENCES labs(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    submission_type VARCHAR(50) NOT NULL,
    status submission_status NOT NULL DEFAULT 'pending',
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    review_notes TEXT
);

CREATE INDEX idx_submissions_user ON submissions(user_id);
CREATE INDEX idx_submissions_drill ON submissions(drill_id);
CREATE INDEX idx_submissions_lab ON submissions(lab_id);
CREATE INDEX idx_submissions_team ON submissions(team_id);
CREATE INDEX idx_submissions_status ON submissions(status);
CREATE INDEX idx_submissions_type ON submissions(submission_type);

CREATE TABLE flag_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    flag_value VARCHAR(255) NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT false,
    points_earned INTEGER NOT NULL DEFAULT 0,
    time_decay_factor DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    hints_used INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_flag_submissions UNIQUE (submission_id, lab_flag_id)
);

CREATE INDEX idx_flag_submissions_flag ON flag_submissions(lab_flag_id);
CREATE INDEX idx_flag_submissions_correct ON flag_submissions(is_correct);

CREATE TABLE evidence_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    objective_id INTEGER REFERENCES lab_objectives(id) ON DELETE SET NULL,
    evidence_type evidence_type NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    description TEXT,
    captured_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_evidence_submissions_objective ON evidence_submissions(objective_id);
CREATE INDEX idx_evidence_submissions_type ON evidence_submissions(evidence_type);

CREATE TABLE report_submissions (
    id SERIAL PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    file_path VARCHAR(500),
    word_count INTEGER,
    quality_score DECIMAL(5,2),
    grade VARCHAR(10)
);

CREATE INDEX idx_report_submissions_quality ON report_submissions(quality_score);

CREATE TABLE submission_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    flag_value VARCHAR(255) NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT false,
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ip_address INET,
    CONSTRAINT uq_submission_attempts UNIQUE (user_id, lab_flag_id, attempt_number)
);

CREATE INDEX idx_submission_attempts_user ON submission_attempts(user_id);
CREATE INDEX idx_submission_attempts_flag ON submission_attempts(lab_flag_id);
CREATE INDEX idx_submission_attempts_submitted ON submission_attempts(submitted_at);

-- ============================================================================
-- MODULE 6: SCORING SYSTEM
-- ============================================================================

CREATE TABLE scores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    total_points INTEGER NOT NULL DEFAULT 0,
    flags_captured INTEGER NOT NULL DEFAULT 0,
    objectives_completed INTEGER NOT NULL DEFAULT 0,
    hints_used INTEGER NOT NULL DEFAULT 0,
    penalty_points INTEGER NOT NULL DEFAULT 0,
    time_bonus_points INTEGER NOT NULL DEFAULT 0,
    first_blood_bonus INTEGER NOT NULL DEFAULT 0,
    completion_time_seconds INTEGER,
    rank_position INTEGER,
    last_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_scores_user_drill UNIQUE (user_id, drill_id),
    CONSTRAINT uq_scores_team_drill UNIQUE (team_id, drill_id)
);

CREATE INDEX idx_scores_user ON scores(user_id);
CREATE INDEX idx_scores_drill ON scores(drill_id);
CREATE INDEX idx_scores_team ON scores(team_id);
CREATE INDEX idx_scores_rank ON scores(rank_position);

CREATE TABLE score_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,
    points_change INTEGER NOT NULL,
    previous_total INTEGER NOT NULL,
    new_total INTEGER NOT NULL,
    details JSONB DEFAULT '{}',
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_score_history_user ON score_history(user_id);
CREATE INDEX idx_score_history_drill ON score_history(drill_id);
CREATE INDEX idx_score_history_team ON score_history(team_id);
CREATE INDEX idx_score_history_recorded ON score_history(recorded_at);

CREATE TABLE first_bloods (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER NOT NULL REFERENCES drills(id) ON DELETE CASCADE,
    lab_flag_id INTEGER NOT NULL REFERENCES lab_flags(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_first_bloods UNIQUE (drill_id, lab_flag_id)
);

CREATE INDEX idx_first_bloods_drill ON first_bloods(drill_id);
CREATE INDEX idx_first_bloods_user ON first_bloods(user_id);

-- ============================================================================
-- MODULE 7: BENCHMARKING SYSTEM
-- ============================================================================

CREATE TABLE benchmarks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    overall_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    offensive_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    defensive_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    web_exploitation_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    network_exploitation_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    active_directory_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    linux_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    windows_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    forensics_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    reporting_score DECIMAL(5,2) NOT NULL DEFAULT 0,
    total_drills_completed INTEGER NOT NULL DEFAULT 0,
    total_flags_captured INTEGER NOT NULL DEFAULT 0,
    average_completion_time_seconds INTEGER,
    last_calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_benchmarks_user UNIQUE (user_id)
);

CREATE INDEX idx_benchmarks_user ON benchmarks(user_id);
CREATE INDEX idx_benchmarks_overall ON benchmarks(overall_score);

CREATE TABLE benchmark_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_id INTEGER REFERENCES drills(id) ON DELETE SET NULL,
    overall_score DECIMAL(5,2) NOT NULL,
    offensive_score DECIMAL(5,2) NOT NULL,
    defensive_score DECIMAL(5,2) NOT NULL,
    web_exploitation_score DECIMAL(5,2) NOT NULL,
    network_exploitation_score DECIMAL(5,2) NOT NULL,
    active_directory_score DECIMAL(5,2) NOT NULL,
    linux_score DECIMAL(5,2) NOT NULL,
    windows_score DECIMAL(5,2) NOT NULL,
    forensics_score DECIMAL(5,2) NOT NULL,
    reporting_score DECIMAL(5,2) NOT NULL,
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_benchmark_history_user ON benchmark_history(user_id);
CREATE INDEX idx_benchmark_history_drill ON benchmark_history(drill_id);
CREATE INDEX idx_benchmark_history_calculated ON benchmark_history(calculated_at);

-- ============================================================================
-- MODULE 8: REPORTING SYSTEM
-- ============================================================================

CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    status report_status NOT NULL DEFAULT 'draft',
    report_type VARCHAR(50) NOT NULL DEFAULT 'after_action',
    quality_score DECIMAL(5,2),
    grade VARCHAR(10),
    word_count INTEGER,
    file_path VARCHAR(500),
    submitted_at TIMESTAMP WITH TIME ZONE,
    graded_at TIMESTAMP WITH TIME ZONE,
    graded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    instructor_feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reports_drill ON reports(drill_id);
CREATE INDEX idx_reports_user ON reports(user_id);
CREATE INDEX idx_reports_team ON reports(team_id);
CREATE INDEX idx_reports_status ON reports(status);
CREATE INDEX idx_reports_quality ON reports(quality_score);

CREATE TABLE report_findings (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    severity severity_level NOT NULL,
    category VARCHAR(50),
    evidence TEXT,
    impact TEXT,
    recommendation TEXT,
    cvss_score DECIMAL(3,1),
    cwe_id VARCHAR(20),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_report_findings_report ON report_findings(report_id);
CREATE INDEX idx_report_findings_severity ON report_findings(severity);

CREATE TABLE evidence (
    id SERIAL PRIMARY KEY,
    finding_id INTEGER NOT NULL REFERENCES report_findings(id) ON DELETE CASCADE,
    evidence_type evidence_type NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100),
    description TEXT,
    captured_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evidence_finding ON evidence(finding_id);
CREATE INDEX idx_evidence_type ON evidence(evidence_type);

-- ============================================================================
-- MODULE 9: LEARNING PATH SYSTEM
-- ============================================================================

CREATE TABLE learning_paths (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    difficulty lab_difficulty NOT NULL DEFAULT 'beginner',
    estimated_duration_hours INTEGER,
    is_public BOOLEAN NOT NULL DEFAULT true,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_learning_paths_name ON learning_paths(name);
CREATE INDEX idx_learning_paths_difficulty ON learning_paths(difficulty);

CREATE TABLE learning_path_modules (
    id SERIAL PRIMARY KEY,
    learning_path_id INTEGER NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_learning_path_modules_path ON learning_path_modules(learning_path_id);

CREATE TABLE learning_path_labs (
    id SERIAL PRIMARY KEY,
    module_id INTEGER NOT NULL REFERENCES learning_path_modules(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    is_required BOOLEAN NOT NULL DEFAULT true,
    min_score INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_learning_path_labs UNIQUE (module_id, lab_id)
);

CREATE INDEX idx_learning_path_labs_module ON learning_path_labs(module_id);
CREATE INDEX idx_learning_path_labs_lab ON learning_path_labs(lab_id);

CREATE TABLE user_learning_progress (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    learning_path_id INTEGER NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES learning_path_modules(id) ON DELETE CASCADE,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    status learning_path_status NOT NULL DEFAULT 'not_started',
    score INTEGER,
    completed_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_learning_progress UNIQUE (user_id, learning_path_id, module_id, lab_id)
);

CREATE INDEX idx_user_learning_progress_user ON user_learning_progress(user_id);
CREATE INDEX idx_user_learning_progress_path ON user_learning_progress(learning_path_id);
CREATE INDEX idx_user_learning_progress_status ON user_learning_progress(status);

CREATE TABLE lab_skills (
    id SERIAL PRIMARY KEY,
    lab_id INTEGER NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50) NOT NULL,
    proficiency_level VARCHAR(20) NOT NULL DEFAULT 'intermediate',
    CONSTRAINT uq_lab_skills UNIQUE (lab_id, skill_name)
);

CREATE INDEX idx_lab_skills_lab ON lab_skills(lab_id);
CREATE INDEX idx_lab_skills_category ON lab_skills(skill_category);

-- ============================================================================
-- MODULE 10: ADMIN AND AUDIT SYSTEM
-- ============================================================================

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    action audit_action NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_username VARCHAR(100),
    resource_type VARCHAR(50),
    resource_id INTEGER,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_actor ON audit_logs(actor_id);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);

CREATE TABLE system_notifications (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    notification_type notification_type NOT NULL DEFAULT 'info',
    target_audience VARCHAR(50) NOT NULL DEFAULT 'all',
    is_active BOOLEAN NOT NULL DEFAULT true,
    starts_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_system_notifications_type ON system_notifications(notification_type);
CREATE INDEX idx_system_notifications_active ON system_notifications(is_active);
CREATE INDEX idx_system_notifications_expires ON system_notifications(expires_at);

CREATE TABLE user_notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_id INTEGER NOT NULL REFERENCES system_notifications(id) ON DELETE CASCADE,
    is_read BOOLEAN NOT NULL DEFAULT false,
    read_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_notifications UNIQUE (user_id, notification_id)
);

CREATE INDEX idx_user_notifications_user ON user_notifications(user_id);
CREATE INDEX idx_user_notifications_read ON user_notifications(is_read);

CREATE TABLE platform_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value JSONB NOT NULL,
    description TEXT,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_platform_settings_key ON platform_settings(setting_key);

CREATE TABLE lab_environment_logs (
    id SERIAL PRIMARY KEY,
    drill_id INTEGER REFERENCES drills(id) ON DELETE CASCADE,
    lab_id INTEGER REFERENCES labs(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    resource_name VARCHAR(100) NOT NULL,
    details JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lab_environment_logs_drill ON lab_environment_logs(drill_id);
CREATE INDEX idx_lab_environment_logs_lab ON lab_environment_logs(lab_id);
CREATE INDEX idx_lab_environment_logs_event ON lab_environment_logs(event_type);
CREATE INDEX idx_lab_environment_logs_created ON lab_environment_logs(created_at);

CREATE TABLE security_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    severity severity_level NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ip_address INET,
    user_agent TEXT,
    details JSONB DEFAULT '{}',
    is_resolved BOOLEAN NOT NULL DEFAULT false,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolution_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_security_events_type ON security_events(event_type);
CREATE INDEX idx_security_events_severity ON security_events(severity);
CREATE INDEX idx_security_events_user ON security_events(user_id);
CREATE INDEX idx_security_events_resolved ON security_events(is_resolved);
CREATE INDEX idx_security_events_created ON security_events(created_at);

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_profiles_updated_at BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_teams_updated_at BEFORE UPDATE ON teams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_labs_updated_at BEFORE UPDATE ON labs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_drills_updated_at BEFORE UPDATE ON drills
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_reports_updated_at BEFORE UPDATE ON reports
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_learning_paths_updated_at BEFORE UPDATE ON learning_paths
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_platform_settings_updated_at BEFORE UPDATE ON platform_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

CREATE VIEW leaderboard AS
SELECT 
    u.id AS user_id,
    u.username,
    u.role,
    COALESCE(SUM(s.total_points), 0) AS total_points,
    COALESCE(SUM(s.flags_captured), 0) AS total_flags,
    COUNT(DISTINCT s.drill_id) AS drills_completed,
    b.overall_score AS benchmark_score
FROM users u
LEFT JOIN scores s ON u.id = s.user_id
LEFT JOIN benchmarks b ON u.id = b.user_id
WHERE u.is_active = true AND u.deleted_at IS NULL
GROUP BY u.id, u.username, u.role, b.overall_score
ORDER BY total_points DESC;

CREATE VIEW active_drills AS
SELECT 
    d.*,
    l.title AS lab_title,
    COUNT(DISTINCT dp.user_id) AS participant_count,
    COUNT(DISTINCT dt.team_id) AS team_count
FROM drills d
LEFT JOIN labs l ON d.lab_id = l.id
LEFT JOIN drill_participants dp ON d.id = dp.drill_id
LEFT JOIN drill_teams dt ON d.id = dt.drill_id
WHERE d.status = 'active' AND d.deleted_at IS NULL
GROUP BY d.id, l.title;

CREATE VIEW user_statistics AS
SELECT 
    u.id AS user_id,
    u.username,
    u.email,
    u.role,
    COUNT(DISTINCT s.drill_id) AS drills_participated,
    COALESCE(SUM(s.total_points), 0) AS total_points,
    COALESCE(SUM(s.flags_captured), 0) AS total_flags,
    b.overall_score,
    b.offensive_score,
    b.defensive_score,
    COUNT(DISTINCT ulp.learning_path_id) AS learning_paths_started,
    COUNT(DISTINCT CASE WHEN ulp.status = 'completed' THEN ulp.id END) AS learning_paths_completed
FROM users u
LEFT JOIN scores s ON u.id = s.user_id
LEFT JOIN benchmarks b ON u.id = b.user_id
LEFT JOIN user_learning_progress ulp ON u.id = ulp.user_id
WHERE u.is_active = true AND u.deleted_at IS NULL
GROUP BY u.id, u.username, u.email, u.role, b.overall_score, b.offensive_score, b.defensive_score;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE users IS 'Main user accounts table';
COMMENT ON TABLE labs IS 'Training labs and scenarios';
COMMENT ON TABLE drills IS 'Cyber drill exercise instances';
COMMENT ON TABLE teams IS 'User teams for collaborative exercises';
COMMENT ON TABLE scores IS 'Current scores for users/teams in drills';
COMMENT ON TABLE benchmarks IS 'Skill benchmark scores for users';
COMMENT ON TABLE reports IS 'After-action reports and assessments';
COMMENT ON TABLE audit_logs IS 'System audit trail for all actions';

-- End of schema
```
## 13. Roadmap

| Feature | Priority | Effort | Target |
|---------|----------|--------|--------|
| AI-assisted feedback (LLM hints, recs, analysis) | High | Medium | Q4 2026 |
| Automated report grading | High | Medium | Q4 2026 |
| Blue-team SIEM integration (Splunk, then Elastic) | High | High | Q1 2027 |
| Live attack simulation (Caldera) | Medium | High | Q1 2027 |
| Custom lab builder | Medium | High | Q2 2027 |
| Certification-style assessment | Medium | Medium | Q2 2027 |
| Organization dashboard | Low | Medium | Q3 2027 |
| External tool integration (Nessus, Metasploit, TheHive, MISP, Slack, Moodle) | Low | Medium | Q3 2027 |

## 14. Status & History

v2 migration complete Sep 4, 2026: 50 new tables (64 w/ legacy), 11-15 enums,
120+ indexes, 3 views (leaderboard, active_drills, user_statistics), 8
`updated_at` triggers; 66-97 v2 endpoints (users/labs/drills/teams/scoring/
reports) alongside v1 with zero breaking changes; SQLAlchemy models
(`models_oxblood.py`, ~1,103 lines). Strategy was gradual (old + new models side
by side). Point-in-time logs (`IMPLEMENTATION-PROGRESS/SUMMARY,
MIGRATION-STATUS, V2-API-SUCCESS`) were squashed into this section — see git
history for the originals.
