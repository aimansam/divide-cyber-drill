# System Architecture

The **div:ide Cyber Range** is a lightweight, self-hosted cyber-range and attack simulation platform designed to run exercises against Proxmox VE clusters with audit logging, live telemetry, and scoring.

---

## 1. High-Level Component Overview

```
                          ┌───────────────────────────┐
                          │   Browser / Web Portal    │
                          │   React 19 + TypeScript   │
                          │   (SPA via Vite bundle)   │
                          └─────────────┬─────────────┘
                                        │ HTTP / SSE / WS Proxy
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ FastAPI API Server & Orchestrator                                       │
│                                                                         │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │  Auth & RBAC   │  │ Scenario Engine  │  │   Drill Runner Engine   │  │
│  │ (argon2id/JWT) │  │  (YAML Parser)   │  │ (PVE Node Orchestrator) │  │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘  │
│                                                                         │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │ Scoring Engine │  │ Redis Event Bus  │  │    noVNC WS Proxy       │  │
│  │ (Decay/Decaps) │  │ (SSE Telemetry)  │  │  (PVE Ticket Handshake) │  │
│  └────────────────┘  └──────────────────┘  └─────────────────────────┘  │
└──────────────┬──────────────────┬──────────────────────────┬────────────┘
               │                  │                          │
               ▼                  ▼                          ▼
    ┌────────────────────┐ ┌─────────────┐        ┌───────────────────────┐
    │ PostgreSQL Storage │ │ Redis PubSub│        │   Proxmox VE Cluster  │
    │  - Audit Logs      │ │  - Events   │        │  - VM / LXC Spawner   │
    │  - Exercises & Runs│ │  - Workers  │        │  - SDN & Linux Bridges│
    │  - Flags & Scores  │ │  - RateLimit│        │  - VNC Console Ports  │
    └────────────────────┘ └─────────────┘        └───────────────────────┘
```

---

## 2. Web Portal Architecture (`/`)

The portal is a lightweight React 19 single-page application built with Vite, TailwindCSS, and Lucide icons. It is served directly by FastAPI under `/` from pre-built static assets.

### Tab Organization
The UI organizes features into distinct operational views:

| View Tab | Primary Functions | Target Role |
|---|---|---|
| **Dashboard** | System KPI cards, recent drill runs, active exercise cards, quick links | All Users |
| **Operate** | Scenario selector, target network topology graph, one-click drill launch & monitor | Operators / Admins |
| **Observe** | Unified live console: VM status, VNC console viewer, kill-chain audit feed, team leaderboard, real-time SOC stream | All Users |
| **Admin** | PVE cluster health, scenario editor/upload, range templates, user & team management | Lead / Admin |
| **History** | Searchable audit trail of past drill runs, debrief reports, score breakdowns | All Users |
| **Profile** | Current user identity, active API tokens, role badges, performance statistics | All Users |

---

## 3. Real-Time Telemetry & Multi-Worker Event Bus

div:ide supports multi-worker deployments (e.g. `uvicorn --workers 4` or horizontal container scaling) through a Redis-backed distributed pub/sub event bus.

```
 Worker 1 (PVE Spawner)                     Worker 2 (Operator SSE Connection)
 ┌──────────────────────┐                   ┌────────────────────────────────┐
 │ runner.py            │                   │ GET /api/v1/runs/{id}/stream   │
 │   emits 'run.started'│                   │                                │
 │         │            │                   │   Subscribed to Redis Channel  │
 └─────────┼────────────┘                   └────────────────┬───────────────┘
           ▼                                                 ▲
     ┌───────────┐      Redis Channel: 'events:run:42'       │
     │ PUBLISH   ├───────────────────────────────────────────┘
     └───────────┘
```

- **In-Memory Fallback**: For single-worker local testing, an in-memory 1024-event ring buffer fanout is used if Redis is unavailable.
- **SSE Streams**: Clients subscribe to `/api/v1/runs/{id}/events/stream` to receive drill state changes, flag capture updates, and SOC kill-chain signals with zero polling latency.
- **Audit Persistence**: Every emitted event is concurrently stored in PostgreSQL (`TelemetryEvent` and `AuditLog` tables) for post-drill after-action review.

---

## 4. noVNC & Console Proxy

Live graphical consoles for target VMs are rendered natively inside the browser via HTML5 canvas and WebSockets without opening PVE ports to end users:

1. Client requests a console session via `GET /api/v1/drills/{id}/assets/{asset_id}/console`.
2. API queries the Proxmox API for a short-lived VNC authentication ticket (`/nodes/{node}/qemu/{vmid}/vncproxy`).
3. Client establishes a WebSocket tunnel (`/ws/console/{vmid}`).
4. API proxy handles the binary RFB protocol stream directly to PVE's VNC endpoint.

---

## 5. Observability & Monitoring

```
  div:ide API Server ──(metrics /metrics)──► Prometheus ──► Grafana
          │
          └──(structured JSON logs)────────► Wazuh / SIEM / syslog
```

- **Prometheus Metrics**: Exposes HTTP request rates, PVE API latency, active VM counts, and runner task queues.
- **Audit Logging**: Every state change, authentication event, and flag submission emits a structured audit record with SHA-256 actor attribution.
- **Health Probes**: `/api/v1/health` provides readiness and liveness probes covering database connectivity, Redis state, and PVE API responsiveness.
