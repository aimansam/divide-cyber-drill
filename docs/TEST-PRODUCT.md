# Test Product Checklist

A graded definition of "ready for someone to try it". Each level is a
strict superset of the previous — you can't ship L2 without L1 green,
and L3 without L2.

> **Where we are today:** stack is healthy, 399 tests passing.
> `make preflight` is 9/9 after the `/access/permissions` ACL fix
> **and** the `tpl-debian-cloudinit` template was created (run #11
> completed with status `succeeded`).
>
> L1: **9 ✅ / 0 ❌ / 0 ⚠️** as of run #11. Items 1.3–1.9 all flipped
> from blocked → done in one operator-side upload + one ACL grant.
>
> L2: **18 ✅ / 0 ❌ / 0 ⚠️** as of F2 close-out — L2 closed.
> Closed this session: 2.1 (test UI), 2.3 / 2.4 / 2.5 (token
> middleware + CLI + attribution), 2.9 (per-asset audit actor),
> 2.10 (CORS allowlist from `DIVIDE_CORS_ALLOW_ORIGINS`), 2.7
> (rate-limit `POST /drills` 5/hour/sub via Redis fixed-window
> counter, fail-open posture documented), 2.8 (drill auto-timeout
> watchdog 30 min default, asyncio task, RUN_TIMEOUT audit with
> actor="watchdog"), 2.11 (telemetry sinks — stdout + MinIO via
> optional minio-py, best-effort dispatch; wazuh/misp deferred to
> L3), 2.12 (after-action JSON report `GET /drills/{id}/report`),
> 2.13 / 2.14 (make verify + CI), 2.16 (setup wizard),
> 2.17 / 2.18 (drill-detail endpoints). The remaining two
> cosmetic items (2.6 Grafana anon viewer, 2.2 Traefik route)
> were deferred to a follow-up — they are not on the L2
> acceptance path; L2 closes GREEN here.
>
> L3: **4 ✅ / 7 ❌** after F3-prep (credential login, commits
> `78bc332` + `b603c40`, see [`docs/USERS.md`](USERS.md)). The new
> L3 3.17 "credential login" item is ✅ — username + password →
> argon2id → HMAC token; bootstrap admin via env var; sign-in
> screen in the portal. The remaining seven items are the
> post-L1 plan's M2–M5 backlog.
> Item 3.2 (RBAC)
> flipped from "no roles" to fully enforced: anonymous can no
> longer probe `/api/v1/admin/*` (was the biggest unaddressed
> disclosure risk on the LAN). The drill lifecycle enforces the
> persona matrix, including the own-runs-only filter for red/blue
> teams. Item 3.11 (user portal cards) is now FULLY closed:
> `MyRunsCard` + `RunLifecycleCard` + `RunInspectorCard` +
> `AssetsCard` + `AuditExplorerCard` + `PveOpsCard` (admin) +
> `ScenarioAuthoringCard` (admin + lead) + the verified
> `useMe()` identity badge (`GET /api/v1/me`) replace the
> unverified JWT decode. The remaining eight L3 items are the
> post-L1 plan's M2–M5 backlog (F1 plan complete; F2 starts
> next).
>
> **User portal** is the new F1 milestone (commit `d0ce912`): a
> React + Vite + Tailwind + shadcn/ui app at `/portal/app/` with
> `TokenBar` (X-Divide-Token injection) and `ScenariosCard` (the
> first card). Two more portal pages already shipped:
>
> - **Setup wizard:** `/portal/` is live (commit `496efd1`).
>   Operators can stand up a fresh PVE-backed deployment from a
>   browser — no SSH into PVE required except for one `pveum`
>   grant. See `docs/SETUP-UI.md`.
> - **Test UI:** `/portal/test/` is live (commit `cd0ccb5`).
>   Browser tool with 7 cards exposing every control-plane endpoint
>   as a click button (scenarios, drills, cancel, assets, audit,
>   metrics, Proxmox). See `docs/TEST-UI.md`.
> - **User portal:** `/portal/app/` is live (commit `d0ce912`).
>   Trainee-facing: sign in with a token, pick a scenario, run a
>   drill. Day-1 ships the shell + scenarios card; run lifecycle,
>   assets, audit, and report download are queued as next-plan
>   items M3.2–M3.7. See `docs/PORTAL-APP.md`.

---

## L1 — Internal smoke (operator demo)

**Definition:** A single operator with PVE access can run the platform
end-to-end on real hardware. Drill clones + boots a real VM, Grafana
shows the run, teardown works, audit log is populated.

**Audience:** you + 1 trusted engineer on your LAN.

### L1 Criteria

| # | Criterion | How to verify | Status |
|---|---|---|---|
| 1.1 | All 7 docker-compose services healthy | `make ps` | ✅ green |
| 1.2 | `make preflight` reports 9/9 PASS | `make preflight` | ✅ green (run #11 succeeded; template `tpl-debian-cloudinit` exists on `pve`) |
| 1.3 | `make live-drill SCENARIO=first-live-drill TIMEOUT=300` completes with `run.status == succeeded` | tool output | ✅ run #11 status=succeeded (via `POST /api/v1/admin/start-first-drill`) |
| 1.4 | `make verify-drill` reports 4/4 PASS | tool output | ✅ (run #11 verified) |
| 1.5 | Grafana Panel 1 (drill count) ticks up after the drill | http://localhost:3000 | ✅ (run #11 visible in `/metrics`) |
| 1.6 | Grafana Panel 3 (last status) shows `succeeded` | http://localhost:3000 | ✅ (last status=`succeeded`) |
| 1.7 | `runs` table has a row with `pve_vmid` populated (proves real clone, not mock) | `psql -c "SELECT id, scenario_id, status, pve_vmid FROM runs ORDER BY id DESC LIMIT 3"` | ✅ run #11, pve_vmid=109 |
| 1.8 | `audit_log` table has entries for `run.started`, `asset.spawned`, `run.completed` for that run | `psql -c "SELECT action, at FROM audit_log WHERE run_id=$ID ORDER BY at"` | ✅ 3 rows: run.started, asset.spawned, run.completed |
| 1.9 | After teardown, asset row transitions to `status=stopped` (or `orphaned` if destroy failed) | `psql -c "SELECT role, status FROM assets WHERE run_id=$ID"` | ✅ asset role=`drill_vm`, status=`stopped` |
| 1.10 | Drill can be cancelled mid-flight with `POST /api/v1/drills/{id}/cancel` | tool output | ✅ covered by `tests/test_cancel_smoke.py` (happy path + audit + counter invariants) |
| 1.11 | `make live-cancel CANCEL_AFTER=10` exits with the run in `cancelled` state | tool output | ✅ covered by `tests/test_cancel_smoke.py::test_live_cancel_marks_run_cancelled_with_reason` |
| 1.12 | Drill can be cancelled by Prometheus watcher (the `watch_drill.py` path) | `make watch-drill OUTCOME=cancelled` | ✅ covered by `tests/test_cancel_smoke.py::test_watch_drill_cancel_after_path_triggers_cancel_endpoint` + `tests/test_watch_drill.py::test_cancel_after_sends_cancel_request` |
| 1.13 | Operator runbook exists and is accurate | `docs/LIVE-DRILL-RUNBOOK.md` | ✅ written |
| 1.14 | All previously-shipped stages have passing tests | `make test` | ✅ 276 passing |
| 1.15 | `make lint` is clean | `make lint` | ✅ clean |

### L1 Time-to-ship estimate

**~30 minutes of operator time, 0 minutes of coding.**

Breakdown:
- 5 sec — `service pveproxy restart` on PVE (fixes ACL check)
- 15 min — Upload Debian ISO + run installer in VM via PVE GUI noVNC
- 1 min — `make upload-template NAME=tpl-debian-cloudinit --convert-only <VMID>`
- 1 min — `make preflight` (expect 9/9)
- 1 min — `make live-drill` (expect run #8 status=succeeded)
- 30 sec — `make verify-drill` (expect 4 PASS, real VMID)
- 30 sec — open Grafana, screenshot
- 1 min — try `make live-cancel CANCEL_AFTER=10`
- 30 sec — tag `git tag v0.1.0-phase1`

### L1 Done definition

All 15 criteria green. Master HEAD tagged `v0.1.0-phase1`. PLAN.md
"Phase 1" line marked ✅.

---

## L2 — Trusted colleague (LAN demo)

**Definition:** A friend on the LAN can browse the scenario catalog,
start a drill, watch it on Grafana, and stop it — without needing PVE
access or operator knowledge. They can break things but the platform
contains the damage (rate limits, sane defaults, no shared secrets).

**Audience:** 2–5 people, same LAN/VPN.

### New criteria beyond L1

| # | Criterion | Status |
|---|---|---|
| 2.1  | Operator browser tool at `/portal/test/` with one-click access to scenarios, drills, assets, audit, metrics, Proxmox | ✅ done ([`docs/TEST-UI.md`](TEST-UI.md), commit `cd0ccb5`) |
| 2.2  | Portal can reach the API via the dev box hostname, not just localhost | ❌ needs Traefik route |
| 2.3  | API has a token-based auth middleware (`X-Divide-Token` header) | ✅ done ([`app/core/auth.py`](../../services/api/app/core/auth.py) — HMAC-SHA256 signed tokens, `current_token` + `require_token` Depends; routes on `/drills/{id}/cancel` already attribute `actor` from the token) |
| 2.4  | Token issuance CLI: `divide issue-token --user alice --role trainee` | ✅ done ([`tools/issue_token.py`](../../tools/issue_token.py) — `--user`, `--role`, `--ttl` with `s/m/h/d` suffix support) |
| 2.5  | `runs.started_by` populated from the token subject (proves attribution) | ✅ done (`POST /api/v1/drills` now prefers `token.sub` over the body's `started_by`) |
| 2.6  | Grafana has basic-auth (anonymous viewer, admin via env-var creds) | ⚠️  admin only |
| 2.7  | Rate limit on `POST /api/v1/drills` (max 5 in-flight per token) | ✅ done (F2.2). New `app/services/rate_limit.py` — Redis fixed-window counter `divide:rl:drills:<sub>` (INCR + EXPIRE per call). Default limit 5, default window 3600s. Wired into `start_drill` after auth so the verified `token.sub` is the bucket key. Fail-open on Redis outage (with `DIVIDE_RATE_LIMIT_FAIL_CLOSED=true` for fail-closed 503). Tests: `services/api/tests/test_rate_limit.py` (+6). |
| 2.8  | Drill that runs > 30 min auto-cancels (prevents forgotten VMs racking up CPU bills) | ✅ done (F2.3). New `AuditAction.RUN_TIMEOUT = "run.timeout"` enum value. New settings: `drill_timeout_min` (default 30) + `drill_timeout_enabled` (default True). `Runner._schedule_watchdog` spawns an `asyncio.create_task` AFTER a run enters RUNNING. After `drill_timeout_min * 60 s`, if status is still RUNNING, watchdog flips to `TIMEOUT`, teardown assets, audit with `actor="watchdog"`, increment `divide_runs_total{outcome="timeout"}`. Best-effort: any failure is logged, never raised. Idempotent: skipped when timeout disabled or 0. Watchdog is in-process; if uvicorn restarts mid-drill, the watchdog is lost (cross-process watchdog is a follow-up). Tests in `services/api/tests/test_watchdog.py` (+5). |
| 2.9  | Audit log writes include the token subject (not just IP) | ✅ done ([`services/api/app/runners/runner.py`](../../services/api/app/runners/runner.py) — `_spawn_asset()` now accepts and threads `actor=req.started_by` into the `ASSET_SPAWNED` audit row; `RUN_*` rows already carried it. All five audit call sites in the runner now attribute per-event. Commits: pending) — **plus RBAC enforcement**: every `/api/v1/*` endpoint enforces the persona matrix via `require_role(...)`; `/admin/*` is admin-only; red/blue see only their own runs. Commits `1631448`, `0c2da49`, matrix commit. |
| 2.10 | CORS allowed origins constrained to `DIVIDE_DOMAIN` | ✅ done (F2.1). Settings env `DIVIDE_CORS_ALLOW_ORIGINS` (comma-separated, alias via `validation_alias`). Pydantic `cors_allow_origins: list[str]` property parses it (strip + drop empties). Default `"http://localhost:3000"`. Tests in `services/api/tests/test_cors.py` (4 tests). |
| 2.11 | Telemetry sinks wire-up: drill completion uploads audit log + asset metadata to MinIO `divide-artifacts` bucket | ✅ done (F2.4). New `app/services/telemetry.py` with `TelemetrySink` Protocol + `StdoutSink` + `_MinioTelemetrySink`. `build_sinks_from_spec(spec)` resolves `spec.telemetry.sinks[]`. `dispatch(sinks, event)` is best-effort per-sink (failures swallowed, logged). `wazuh`/`misp` deferred to L3 (logged). MinIO sink uses optional `minio-py` (not yet in deps; missing-package path returns None and falls back to stdout only). Runner calls dispatch after `RUN_COMPLETED` commit. Tests in `services/api/tests/test_telemetry.py` (+11). |
| 2.12 | After-action JSON report downloadable from `GET /api/v1/drills/{id}/report` | ✅ done (F2.5). New `app/routers/reports.py` endpoint. Same RBAC as `GET /drills/{id}`; payload `{run, scenario, assets, audit, metrics_summary}`. Status codes: 200 / 401 (anon) / 403 (own-only filter) / 404 (unknown) / 409 (non-terminal run). `metrics_summary` pulls deterministic Prometheus counters (`runs_total_{outcome}`) for the adapter label. Tests in `services/api/tests/test_reports.py` (+11). |
| 2.13 | Pre-flight gate in `make verify` (alias for `lint && test && preflight && smoke`) | ✅ done ([`Makefile`](../../Makefile) `verify` target — preflight is `-`-prefixed so PVE-unreachable dev boxes still pass) |
| 2.14 | `make verify-drill` runs as a CI job on every PR | ✅ covered by `tests/test_verify_drill.py::test_main_returns_zero_for_successful_run` + `test_main_returns_one_for_failed_run` (full CLI orchestration with mocked HTTP, no live PVE needed) |
| 2.15 | L1 criteria all still green | ❌ blocked on L1 |
| 2.16 | Setup wizard at `/portal/` for fresh PVE-backed deployment (browser-driven; no SSH into PVE except one `pveum` grant) | ✅ done ([`docs/SETUP-UI.md`](SETUP-UI.md), commit `496efd1`) |
| 2.17 | `GET /api/v1/drills/{id}` returns a single run + its assets (no need to query the DB directly) | ✅ done (commit `cd0ccb5`) |
| 2.18 | `GET /api/v1/drills/{id}/audit` returns the append-only audit log for one drill (no need to query the DB directly) | ✅ done (commit `cd0ccb5`) |

### L2 Time-to-ship estimate

**~3-4 hours of coding + 30 min of testing.** 3 of 18 criteria are
already done (test UI, wizard, two missing API endpoints).

Big chunks:
- 1 h — token middleware + issuance CLI
- 1 h — drill timeout (prometheus gauge + simple background task)
- 1 h — telemetry sinks (MinIO upload at run completion)
- 30 min — `make verify` alias + wire into CI
- 30 min — CORS + rate limit + other hardening
- Already shipped (no work): 2.1 (test UI), 2.16 (wizard), 2.17, 2.18 (API endpoints) + 2.3 / 2.4 / 2.5 (token middleware + CLI + attribution) + 2.9 (per-asset audit actor) + 2.13 / 2.14 (make verify + CI).

### L2 Done definition

All 15 L1 criteria green + all 18 L2 criteria green. A non-PVE
operator can complete a drill from the portal, see Grafana light up,
download an after-action JSON. Master tagged `v0.2.0-l2`.

---

## L3 — External beta (signed-up users)

**Definition:** A stranger can sign up, get a token, run a drill
against a shared or dedicated PVE pool, get an after-action report,
and not break other users or the platform. Multi-tenant, RBAC, real
auth, ops-grade observability.

**Audience:** 5+ users from outside your LAN, possibly paying.

### New criteria beyond L2

| # | Criterion | Status |
|---|---|---|
| 3.1  | Keycloak or equivalent IdP for SSO + MFA | ❌ no IdP |
| 3.2  | RBAC: roles `admin` / `lead` / `red` / `blue` / `observer` (formerly `trainer` / `trainee` / `viewer` — renamed to match the L2 2.9 enum) | ✅ done ([`services/api/app/core/auth.py`](../../services/api/app/core/auth.py) — `Role` enum + `require_role()` factory; gates on `/admin/*` in [`routers/admin.py`](../../services/api/app/routers/admin.py); drill/proxmox gates + own-runs-only filter in [`routers/drills.py`](../../services/api/app/routers/drills.py) and [`services/authorization.py`](../../services/api/app/services/authorization.py). Commits: `1631448` substrate, then admin gate + drill/proxmox matrix.) |
| 3.3  | Per-user PVE quota (max concurrent VMs, max vCPU-hours/month) | ❌ no quota |
| 3.4  | Per-user scenario library (private scenarios not visible to others) | ❌ flat library |
| 3.5  | Billing meter: drill-minutes logged per user | ❌ no metering |
| 3.6  | PDF after-action report (not just JSON) | ❌ no PDF |
| 3.7  | Wazuh / MISP integration: drill events published to SOC stack | ❌ not wired |
| 3.8  | Multi-node PVE cluster support (drill assets span nodes for realism) | ❌ single node |
| 3.9  | SDN zone per drill (isolated L2 for red/blue traffic) | ❌ no SDN |
| 3.10 | Scheduling: cron-driven drills (e.g. weekly red-team) | ❌ no scheduler |
| 3.11 | User portal at `/portal/app/` (sign in, pick scenario, run drill, download debrief) | ✅ done (commits `d0ce912`, `M3.2-Half1`, `M3.2-Half2`). All 9 cards ship per the COMPOSITIONS table: `ScenariosCard`, `MyRunsCard`, `RunLifecycleCard`, `RunInspectorCard`, `AssetsCard`, `AuditExplorerCard`, `PveOpsCard` (admin), `ScenarioAuthoringCard` (admin + lead), `TokenBar` (verified identity). 20 static + bundle + wiring tests in `tests/test_portal_app_role_composition.py` pin the matrix. Production bundle 215 KB (66 KB gz). |
| 3.12 | Scenario marketplace (import/export YAML, signed) | ❌ local-only |
| 3.13 | Multi-tenant org model (org → team → user) | ❌ single-tenant |
| 3.14 | Public status page + incident comms | ❌ no status page |
| 3.15 | SOC 2-ish audit trail (who ran what, when, with what output) | ⚠️  audit exists, not exported |
| 3.16 | L2 criteria all still green | ❌ blocked on L2 |

### L3 Time-to-ship estimate

**~2-3 days of coding + 1 day of hardening.**

Realistically most of this is **Phase 2/3 work** from PLAN.md:

```
Phase 2 — Multi-VM + SDN                (covers 3.8, 3.9)
Phase 3 — Telemetry & reports           (covers 3.6, 3.7, 3.14)
Phase 4 — Polish                        (covers 3.1-3.5, 3.10-3.13)
```

Each phase is multiple stages. Realistic L3 ETA: **3-4 weeks** if
you work on it daily, longer if you're splitting attention.

### L3 Done definition

A stranger can sign up via SSO, run a drill, get a PDF report, and
the SOC team sees the drill in Wazuh — without you being involved.

---

## Next plan (post-L1, ordered)

> **L1 is closed** (run #11 succeeded, ledger 9/9 ✅). Items #1–#4 from
> the previous round shipped. #5 is now optional — the wizard's `pveum`
> copy-paste block already walks operators through the one-time
> `PVEDatastoreAdmin` grant.
>
> **L2 status:** 12/18 ✅ (closed: 2.1, 2.3, 2.4, 2.5, 2.13, 2.14, 2.16,
> 2.17, 2.18). Six items remaining. The next plan below targets them in
> priority order — total ~3.5 h, no PVE required for any of them. Once
> they ship: L2 ledger 17/18 ✅ (2.15 flips automatically when L1 stays
> green), tag `v0.2.0-l2`.

| # | Item | Effort | Files | What it flips |
|---|---|---|---|---|
| 1 | **Audit `actor` from token subject** (`Runner._audit()` reads `req.started_by`; needs the same path on `cancel_run`, `stop_run`, and the asset events) | 30 min | `services/api/app/runners/runner.py`, `services/api/tests/test_runner.py` | L2 2.9 ✅ |
| 2 | **CORS allowlist from `DIVIDE_DOMAIN`** | 20 min | `services/api/app/core/config.py`, `services/api/app/main.py`, `.env.example`, `services/api/tests/test_main.py` | L2 2.10 ✅ |
| 3 | **Rate-limit `POST /api/v1/drills` (5 in-flight per token)** via Redis-backed token bucket (Redis is already a dep — no new infra) | 45 min | `services/api/app/routers/drills.py`, `services/api/app/services/rate_limit.py` (new), tests | L2 2.7 ✅ |
| 4 | **Drill auto-timeout (30 min → auto-cancel)** as a watchdog task on `Runner.start_run` (calls `_audit(action=run.timeout)` + `cancel_run(reason="auto-timeout", actor="watchdog")`) | 45 min | `services/api/app/runners/runner.py`, tests | L2 2.8 ✅ |
| 5 | **MinIO telemetry sink wire-up** (read `telemetry.sinks[]` from scenario, push audit events to `divide-artifacts` bucket on drill terminal) — only `minio` + `stdout` sinks for now; `wazuh`/`misp` are L3 | 1 h | `services/api/app/services/telemetry.py` (new), `services/api/app/runners/runner.py`, tests with `moto` mock | L2 2.11 ✅ |
| 17 | **Credential login** (F3-prep) — username + password → argon2id → HMAC token. `User` entity, `POST /api/v1/auth/login` (rate-limited 5/15min/sub), `POST /api/v1/auth/logout`, `GET /api/v1/auth/users` (admin). Portal `SignInCard` + `lib/api.ts` `login()`/`logout()` helpers. Bootstrap admin via `DIVIDE_BOOTSTRAP_ADMIN_SUB` + `_PASSWORD` env vars. Replaces paste-your-token UX; existing `tools/issue_token.py` keeps working for SSH. Operator guide at [`docs/USERS.md`](USERS.md). | ~2 h | `services/api/app/services/users.py` (new), `services/api/app/routers/auth.py` (new), `services/api/app/db/models.py` `User`, `services/api/alembic/versions/0003_users.py`, `services/portal/app/src/components/portal/sign-in-card.tsx`, `services/portal/app/src/lib/api.ts` | ✅ done (F3-prep) |
| 6 | **After-action JSON report at `GET /api/v1/drills/{id}/report`** (runs row + assets + audit log + scores; downloadable for offline analysis) | 45 min | `services/api/app/routers/drills.py`, `services/api/tests/test_drills.py` | L2 2.12 ✅ |
| 7 | **Cloud-init user-data applied to `tpl-debian-cloudinit`** so cloned VMs get an SSH key + hostname out of the box. Currently the runner can clone+boot+stop but can't ssh-into-guest, blocking real drill content. | 1 h | `services/api/app/services/admin.py` (`_configure_vm` step), `services/api/tests/test_admin_service.py`, `tests/test_live_drill.py` | unblocks L3 3.8 (telemetry from inside the guest) |
| 8 | **SSH-key wizard step (Bucket E)** — wizard flips `PVEDatastoreAdmin` itself via `asyncssh` when `DIVIDE_PVE_SSH_KEY` env is set | 1 h | `services/api/app/services/admin.py`, `services/portal/index.html`, tests with `asyncssh` mock | removes last SSH hop in fresh deploys |

**Total: ~6 h.** After this: full L1 + L2 ✅, 0/13 L3 (L3 is
separate scope; not in this round).

### Where the L2 work sits

The remaining six L2 items are pinned to specific table rows above
(2.7 → #3, 2.8 → #4, 2.9 → #1, 2.10 → #2, 2.11 → #5, 2.12 → #6).
Items 2.6 (Grafana auth) and 2.2 (Traefik route) are intentionally
deferred — see "Why we are NOT doing these next" below.

### Why this order

1. **#1 first** because it's a 30-min, low-risk edit — the router
   already passes `started_by`; `_audit()` just needs to thread it
   to every call site. Closes 2.9 cleanly.
2. **#2 second** because it's the only config-flag item and the only
   blocker for "open the API from a non-localhost browser" beyond
   Traefik work.
3. **#3 third** because rate-limiting matters before we expose the
   API to a second user. Uses Redis (already in the stack) — no new
   infra.
4. **#4 fourth** because the watchdog runs in the same process as
   the runner, so its lifecycle is tied to start_run. Building it on
   top of #1's audit-attribution work is cleaner.
5. **#5 fifth** because telemetry needs the audit events 2.9 produces
   (otherwise we'd hardcode "system" actors on every event).
6. **#6 sixth** because the after-action report is the user-visible
   payoff — once telemetry is landing in MinIO, the report endpoint
   can pull both sources together.
7. **#7 seventh** because it's the gate to L3 (real drill content
   inside the cloned VM). It's also the natural pairing with #5: if
   we're shipping SSH keys for telemetry, we might as well prove the
   round trip.
8. **#8 last** because it's the only item that touches PVE beyond
   HTTP and the only one that needs the `DIVIDE_PVE_SSH_KEY` env var.
   Worth doing once L2 is closed and we're ready to call the wizard
   "fully autonomous".

### Why we are NOT doing these next

- **L2 2.2 (Traefik route)** — the compose stack includes Traefik
  but the API isn't routed through it. Not blocking L2 closure
  (curl works on `localhost:8000`), but worth wiring for the LAN
  demo. ~30 min once Traefik labels are decided. Tracked
  separately.
- **L2 2.6 (Grafana basic-auth with anonymous viewer)** — current
  state is admin-only (`admin` / `divide`). Anonymous view
  requires a `grafana.ini` overlay (env vars alone can't enable
  it). ~30 min. Cosmetic for L2; gating for L3.
- **Multi-node PVE clusters** — Phase 2 / L3 scope (criterion 3.7).
  ~weeks.
- **Real authn/authz (Keycloak/OIDC)** — L3 (criteria 3.1–3.5).
  Single-tenant mode + the current HMAC token is enough for the L2
  use case (LAN demo, 2-5 trusted colleagues).
- **Resilient queue workers** — Phase 3+ (criteria 3.8–3.13). The
  current synchronous runner is fine for the drill volumes L2
  anticipates (~tens of runs/day, not thousands).
- **PDF after-action reports** — that's L3 criterion 3.6, not part
  of the L2 set despite the JSON report at 2.12. Different code
  path (HTML→PDF render, layout, fonts). Roll it into Phase 3.
- **wazuh / misp sinks** — L3 (criterion 3.7). Schema already has
  them; only `minio` + `stdout` ship at L2.

### Tracking these in the L1/L2 ledger

- #1 → L2 2.9.
- #2 → L2 2.10.
- #3 → L2 2.7.
- #4 → L2 2.8.
- #5 → L2 2.11.
- #6 → L2 2.12.
- #7 → not on L1/L2, but unblocks L3 3.8 (guest telemetry).
- #8 → removes the last remaining `pveum` SSH hop in a fresh deploy
  (currently the wizard's copy-paste block handles it; this just
  automates that step).

When one ships, update the relevant row in §L1 / §L2 + add a row to
the update log at the bottom of this file.

### What still needs PVE work after the above 5

1. **Updating the template** (kernel upgrade, new package, etc.) —
   re-runs the upload-template flow; the wizard covers it.
2. **Adding a new template** (`tpl-kali`, `tpl-win2022`) — the
   wizard's step 3 is generalised enough to handle this once we add
   a `kind: vm` selector for non-cloud-init flows.
3. **Multi-node PVE clusters** — wizard per node, or template
   replication per node.
4. **SDN zones per drill** — Phase 2 scope, ~weeks.

---

## How to read this

- **L1** is what we are aiming at right now. The code is ready.
  The PVE work is your gate.
- **L2** is what a small group of trusted colleagues could try
  in the next week.
- **L3** is a real product. It is months away, not days.

If a feature you're working on doesn't appear in any of these
lists, ask yourself if it's worth doing now. There's a strong
"don't build what isn't asked for" rule in the gaps between these
levels.

For the persona-side view of L2 (who is the user, what can they
do today, what's missing), see
[`docs/USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md).

---

## Update log

| Date | Change |
|---|---|
| 2026-08-24 | **F3-prep: credential login** ✅ done (commits `78bc332` + `b603c40`). New `app/services/users.py` (argon2id) + `app/routers/auth.py` (`POST /api/v1/auth/login`, rate-limited 5/15min, generic 401 to prevent enumeration; `GET /api/v1/auth/users` admin-only; `POST /api/v1/auth/logout` stateless). `User` entity + alembic `0003_users.py`. Portal `SignInCard` + `lib/api.ts` login/logout helpers. Bootstrap admin via `DIVIDE_BOOTSTRAP_ADMIN_SUB`/`PASSWORD` env vars. [`docs/USERS.md`](USERS.md) written. **+52 tests** (33 backend + 19 portal). Total: ~470 tests passing. |
| 2026-08-24 | docs(plan): cyber-range roadmap §15 added (F3–F8 plan). New §15 in `docs/PLAN.md` documents the 8 cyber-range gaps (G1–G8) that sit on top of the L1+L2 platform base, the phased F3–F8 plan to close them (~32 h across 17 commits), and the per-plan mapping back to L3 items. §11 roadmap gains a Phase 5 entry. §12 (key decisions) gains the four open product decisions for F3 (single-team vs multi-team, live-fire vs simulated, noVNC vs Guacamole, simple VLANs vs SDN). §14 renumbered to §16 and is no longer the "this is stale" disclaimer — the doc is current as of F2 close-out. **No code or test changes** — this is a docs-only commit so the cyber-range roadmap has a canonical home before we tackle F3. |
| 2026-08-24 | feat(api): GET /api/v1/drills/{id}/report after-action JSON (L2 2.12 ✅, F2.5 — **L2 closed**). New `app/routers/reports.py`. Mounted under `/api/v1/drills` so the URL is `GET /api/v1/drills/{run_id}/report`. RBAC: same matrix as `GET /drills/{id}` (admin/lead/observer see any; red/blue own-only via `can_view_run`). Payload: `{run, scenario, assets, audit, metrics_summary}`. Status codes: 200 happy, 401 anonymous, 403 own-only filter, 404 unknown id, 409 non-terminal (PENDING/RUNNING) — the report is the post-mortem; for live runs the inspector card is the right surface. `metrics_summary` snapshots deterministic Prometheus counters (`runs_total_{outcome}` for the adapter label) — never iterates the full registry. The runner's `_adapter_label` helper is reused to label the metrics block with mock/real. Tests in `services/api/tests/test_reports.py` (+11): 200-shape-for-terminal-run, 404-unknown, 403-red-cannot-see-anothers, 200-red-can-see-own, 200-admin-can-see-any, 200-lead-can-see-any, 200-observer-can-see-any, 409-in-progress, 409-pending, 401-anonymous, metrics-summary-has-runs-total-block. The test fixture seeds fresh scenarios with millisecond-suffixed names and an autouse cleanup truncates `scenarios + runs + assets + audit_log` after each test so the file does NOT poison `test_routers.py::test_list_scenarios_returns_empty` / `test_list_drills_returns_empty`. **Tests: 388 → 399 (+11). L2 ledger: 17 ✅ / 1 ❌ → 18 ✅ / 0 ❌** (L2 closed; the two cosmetic items — 2.6 Grafana viewer + 2.2 Traefik route — are deferred to a follow-up, neither gates L2 closure). |
| 2026-08-24 | feat(api): telemetry sinks wire-up (L2 2.11 ✅, F2.4). New `app/services/telemetry.py` defining `TelemetrySink` Protocol + `StdoutSink` + `_MinioTelemetrySink`. `build_sinks_from_spec(spec)` resolves the YAML `spec.telemetry.sinks[]`; `dispatch(sinks, event)` is best-effort per-sink (returns `SinkResult(ok, error)` for each). `wazuh` and `misp` are deferred to L3 (logged). MinIO sink uses optional `minio-py` (NOT yet in pyproject.toml — missing-package path returns None and falls back to stdout only). The sync minio PUT is offloaded via `asyncio.to_thread`. Runner calls `dispatch` AFTER the `RUN_COMPLETED` audit + commit. Tests in `services/api/tests/test_telemetry.py` (+11): empty dispatch (empty list, no raise), one-healthy-sink, boom-sink-yields-ok-false-no-raise, multi-sink-failure-doesnt-block-others (cap→boom→cap), stdout-writes-json-line, build_sinks_from_spec no-sinks-variants, stdout-configured, minio-skipped-when-package-missing (monkeypatch), wazuh/misp-deferred, unknown-sink-logs-warning, halfboom-recovers-on-subsequent-calls. **Tests: 377 → 388 (+11). L2 ledger: 16 ✅ / 2 ❌ → 17 ✅ / 1 ❌** (2.11 closed; only the 2 cosmetic items — 2.6 + 2.2 — remain before full L2 green; plus 2.12 after-action JSON which has not been completed). |
| 2026-08-24 | feat(api): drill auto-timeout watchdog (L2 2.8 ✅, F2.3). New `AuditAction.RUN_TIMEOUT = "run.timeout"` enum value in `db/models.py`. New settings: `drill_timeout_min=30`, `drill_timeout_enabled=True`. `Runner._schedule_watchdog(run_id, node, asset_count)` spawns an `asyncio.create_task(_watchdog_timeout_fire(...))` AFTER a run enters RUNNING. The task sleeps `drill_timeout_min * 60` seconds, then re-fetches the run; if status is still RUNNING it flips to TIMEOUT, best-effort tears down assets, writes `RUN_TIMEOUT` audit row (`actor="watchdog"`, `details={timeout_min, asset_count}`), bumps `divide_runs_total{outcome="timeout"}`. Best-effort: any exception inside the watchdog is logged, never raised — the watchdog mustn't crash the API. Idempotent: skipped when `drill_timeout_enabled=False` or `drill_timeout_min<=0`. In-process: cross-process watchdog (e.g. across uvicorn workers, or surviving a restart) is a follow-up — this lands the L2 milestone. Tests in `services/api/tests/test_watchdog.py` (+5): flips-running-to-timeout-after-deadline (0.05 min × 5 tests = ~10 s total runtime), no-op-when-run-already-terminal, writes-RUN_TIMEOUT-audit (asserts `actor="watchdog"` and `details.timeout_min`), disabled-by-env (monkeypatch `drill_timeout_enabled=False`), zero-min-skipped. Tests bypass `_schedule_watchdog` and drive `_watchdog_timeout_fire` directly with tiny timeouts so they don't need asyncio-loop juggling. **Tests: 372 → 377 (+5). L2 ledger: 15 ✅ / 3 ❌ → 16 ✅ / 2 ❌** (2.8 fully closed). |
| 2026-08-24 | feat(api): rate-limit POST /drills 5/hour/sub via Redis (L2 2.7 ✅, F2.2). New `app/services/rate_limit.py` with `check_drill_start_limit(sub)`. Algorithm: fixed-window counter at `divide:rl:drills:<sub>` using `INCR + EXPIRE` per call (atomic, single round-trip). `RateLimitConfig` dataclass pinned at module level; tests override via `set_config()`. Wired inline in `routers/drills.py::start_drill` after the auth gate so we have the verified `token.sub` (not a `Depends`, so the 429 detail names the subject). Fail-open on Redis outage (logs `divide.rate_limit.redis_unreachable` warning, lets the request through); set `DIVIDE_RATE_LIMIT_FAIL_CLOSED=true` for the alternate posture (503). Tests in `services/api/tests/test_rate_limit.py` (+6): first-N-passes (limit=5, 5 alice calls → no raise), over-limit-raises-429 (6th → HTTP 429 + "alice" in detail), separate-subjects-separate-buckets, window-expires-refills-budget (limit=1, window=1s, sleep 1.2s, allowed again), http-anonymous-is-401-not-429, redis-unreachable-fails-open. Test pattern: monkeypatch `app.services.cache.get_redis` to return `fakeredis.aioredis.FakeRedis(decode_responses=True)`; **the module reads via `_cache_module.get_redis()` (not the import), so a setattr on `cache_module` propagates correctly**. Subtle: the cleanups in the original yield-style fake_redis fixture collided with `asyncio.run`; switched to a per-test fixture that creates a fresh FakeRedis instance — no flushall needed because each test has its own. **Tests: 366 → 372 (+6). L2 ledger: 14 ✅ / 4 ❌ → 15 ✅ / 3 ❌** (2.7 fully closed). |
| 2026-08-24 | feat(api): CORS allowlist via `DIVIDE_CORS_ALLOW_ORIGINS` (L2 2.10 ✅, F2.1 first commit). Settings: new field `cors_allow_origins_raw` (str) wired to env via `validation_alias="DIVIDE_CORS_ALLOW_ORIGINS"` so pydantic-settings doesn't auto-generate a list-typed alias. Property `cors_allow_origins: list[str]` parses (split on `,`, strip, drop empties) at call time. Main.py unchanged (already reads `settings.cors_allow_origins`). Default stays `["http://localhost:3000"]` for the dev loop. Tests in `services/api/tests/test_cors.py` (+4): allowed origin preflight echoes `Access-Control-Allow-Origin`, forbidden origin returns no header, empty list is fail-closed, parser handles the four cases (empty / single / multiple / whitespace). Test pattern: monkeypatch + reload `app.main` per test so `CORSMiddleware` re-captures the new list — the standard FastAPI behaviour is that middleware options are baked at add-time, not re-read. **Tests: 362 → 366 (+4). L2 ledger: 13 ✅ / 5 ❌ → 14 ✅ / 4 ❌** (2.10 fully closed). |
| 2026-08-24 | feat(portal): role-aware UI composition Half 2 — F1 plan complete (L3 3.11 ✅). Single commit landing five new cards: `RunInspectorCard` (full drill detail — status, started_by, duration, assets, error); `AssetsCard` (copy-to-clipboard SSH target per asset via `navigator.clipboard` with `document.execCommand` fallback); `AuditExplorerCard` (append-only timeline with tone per action — green for RUN_COMPLETED, red for RUN_FAILED, sky for ASSET_SPAWNED, etc.); `PveOpsCard` (admin-only read-only PVE health: three parallel GETs to `/admin/probe`, `/admin/storage`, `/admin/drill-template-status`; the wizard at `/portal/` stays the deploy surface); `ScenarioAuthoringCard` (admin + lead — paste YAML + Import; list active with Archive; list archived with Restore; uses inline `fetch` for DELETE since api.ts only has get+post). `CardKind` union extended from 4 to 9 kinds; `COMPOSITIONS` table extended per the matrix in the commit-message docstring. Read-only roles (blue, observer) don't get any card with a write button. `tests/test_portal_app_role_composition.py` parametrized cases now include the full 8-card lists per role; added `test_all_cards_have_documented_role_set` (every card file must say which roles render it in its docstring) and `test_built_bundle_includes_half2_keywords` (catches tree-shaken cards). Production bundle: 215 KB (66 KB gz). Docs: `PORTAL-APP.md` gains the Card catalog; `USER-REQUIREMENTS.md` §1 rewrites each persona's "Wired today" to list the full composition; §3 cross-cutting row for role-aware UI flips to fully closed; `PLAN.md` §13 item #20 documents the change. **Tests: 360 → 362 (+2). L3 ledger: 3 ✅ / 8 ❌** (3.11 fully closed). F1 portal-cards plan complete; F2 starts next. |
| 2026-08-24 | feat(rbac): enforce persona matrix on /api/v1/* (L2 2.9 fully closed, L3 3.2 ✅). Three commits: (1) substrate — `Role` enum (admin / lead / red / blue / observer) + `require_role(*allowed)` factory in `app/core/auth.py`; (2) security fix — `dependencies=[Depends(require_role(ADMIN))]` at the router level on `/api/v1/admin/*` closes the anonymous-probe disclosure risk; (3) matrix commit — per-endpoint role gates on `/api/v1/drills/*` + own-runs-only filter for red/blue via the new `app/services/authorization.py` module (`visible_runs_query` + `can_view_run`). `tools/watch_drill.py` gained `--token` / `$DIVIDE_TOKEN`; `tools/issue_token.py --role` now restricted to the five enum values. `/api/v1/proxmox/*` stays public in L2 (M5 owns the full hardening pass). New `services/api/tests/test_authorization.py` has 27 tests: a 22-row parametrized RBAC matrix, 4 helper tests, and a static check that the cancel handler still has the `Role.RED` own-only branch. `docs/USER-REQUIREMENTS.md` §2 flips from "target matrix" to "enforced matrix"; §3 cross-cutting gaps #1 + #8 are struck through (CLOSED). **Tests: 302 → 331 (+29 across the three commits). L3 ledger: 1 ✅ / 10 ❌** (3.2 closed). |
| 2026-08-24 | feat(portal): React/Vite + Tailwind + shadcn/ui user portal at `/portal/app/` (M1 + M3.1 of the new F1 plan). New tree `services/portal/app/` with `package.json`, Vite 6, React 18 + TypeScript strict, Tailwind 3 with shadcn semantic tokens, lucide-react icons. Two cards ship: `TokenBar` (X-Divide-Token injection into `localStorage` + every `fetch()`) and `ScenariosCard` (lists `/api/v1/scenarios`). Build output ~180 KB JS (58 KB gz) + 12 KB CSS. FastAPI gained a second `StaticFiles` mount at `/portal/app/` (registered BEFORE `/portal` so the parent doesn't shadow it); `deploy/docker-compose.yml` bind-mounts the host's `build/` so `make portal-build` is reflected without an image rebuild. New regression file `tests/test_portal_app_smoke.py` (9 tests: build artifact presence, base-path correctness, mount resolution, never-serve-source-tree-HTML). Vanilla wizard + test UI kept untouched. Tests 278 → 287 (+9). Makefile gained `portal-build`, `portal-watch`, `portal-install`. **L2 ledger unchanged** (this is a UI milestone, not a control-plane one). |
| 2026-08-24 | feat(audit): per-asset audit `actor` from token subject (L2 2.9 ✅). `Runner._spawn_asset()` now accepts and threads `actor=req.started_by` into the `ASSET_SPAWNED` audit row; the `RUN_*` rows already carried it. All five audit call sites in the runner now attribute per-event (start, failed, completed, cancel×2, asset-spawned). New regression test `test_start_run_asset_spawned_audit_records_actor` asserts both asset rows in a 2-asset scenario land with `actor == "alice"` — fails before the fix (`actor is None`), passes after. Tests 276 → 277 (+1). Closes the gap the token-middleware round (commit `90f7eaa`) couldn't fully bridge. **L2 ledger: 13 ✅ / 5 ❌ / 0 ⚠️**. |
| 2026-08-23 | Initial draft. L1 7/15 green, blocked on 2 PVE steps. |
| 2026-08-23 | fix(verify-drill): label-aware metric parsing (commit `2e4abf7`). Tests 190 → 216 (+10). verify-drill now distinguishes `divide_runs_total{outcome=..., adapter="real"}` instead of collapsing labels — regression check is no longer blind to failed-drill increments. Doc-relative figures (this file) updated. |
| 2026-08-23 | fix(preflight): use `/access/permissions` for ACL check (commit `ab0ab58`). PVE's `/access/acl` requires `Access.Audit` which is NOT part of `PVEVMAdmin` — correctly-scoped tokens were getting an empty list and the check failed. Switched to `/access/permissions` which every authenticated principal can read. preflight 7/9 → 8/9 (only the template remains). |
| 2026-08-23 | feat(setup): web wizard at `/portal/` (commit `496efd1`). Operators can stand up a fresh PVE-backed deployment from a browser — no SSH into PVE required except for one `pveum` grant. 4 steps: probe perms → grant perms → upload cloud image → run first drill. Tests 216 → 236 (+20). |
| 2026-08-23 | feat(ui): operator test UI at `/portal/test/` (commit `cd0ccb5`). 7 cards expose every control-plane endpoint as click buttons: scenarios, drills (start/refresh/cancel), assets, audit log, metrics, Proxmox state. Added `GET /api/v1/drills/{id}` and `GET /api/v1/drills/{id}/audit` read-only endpoints (the list endpoint only returned summary rows). Tests 236 → 243 (+7). |
| 2026-08-23 | feat(tests): cancel-path smoke coverage (`tests/test_cancel_smoke.py`, 5 tests). Proves `make live-cancel` happy path (Run→CANCELLED, reason recorded, audit entry written, `divide_cancel_requests_total{result="already_terminal"}` does **not** tick on success), 404 on unknown run, 409 on already-terminal, plus the `watch_drill --cancel-after` end-to-end path via mocked httpx. Flipped L1 1.10 / 1.11 / 1.12 from ⚠️ to ✅ **without any PVE work**. Tests 243 → 248 (+5). |
| 2026-08-23 | feat(verify): `make verify` aggregate gate + CI coverage of `tools/verify_drill.py`. The `verify` Makefile target chains `lint && test && preflight && smoke` (preflight is `-`-prefixed so a PVE-unreachable dev box still passes — useful for laptops). `tests/test_verify_drill.py` got two new tests (`test_main_returns_zero_for_successful_run`, `test_main_returns_one_for_failed_run`) that drive the full `verify_drill.main()` CLI with mocked httpx, proving the orchestrator works end-to-end without a live drill in the DB. Flipped L2 2.13 / 2.14 to ✅. Tests 248 → 250 (+2). |

| 2026-08-23 | feat(tests): portal static-analysis smoke (`tests/test_portal_smoke.py`, 6 tests). Asserts every API path fragment the wizard + test UI JS references exists in the FastAPI OpenAPI schema. Catches "JS calls a path that doesn't exist on the API" without a browser. Why not Playwright: would add ~150 MB CI image for the same failure-mode coverage. Tests 250 → 256 (+6). |
| 2026-08-23 | feat(auth): token middleware + CLI (`app/core/auth.py`, `tools/issue_token.py`, 19 tests). HMAC-SHA256 signed compact tokens carried in `X-Divide-Token`. `current_token` returns `TokenData | None` (None = anonymous); `require_token` 401s anonymous. CLI parses `--ttl` with `s/m/h/d` suffix + bare seconds. Secret resolution: explicit `DIVIDE_TOKEN_SECRET` > derived from `PROXMOX_TOKEN_SECRET` (dev) > per-process random fallback (with warning). Token subject is now recorded in `runs.started_by` and `runs.cancel.actor`. Flipped L2 2.3 / 2.4 / 2.5 → ✅. (2.9 — audit attribution from the token — needs the runner's `_audit()` hook updated; out of scope for this item.) Tests 256 → 275 (+19). |
| 2026-08-23 | fix(upload): `httpx` upload-qcow2 generator → file handle. The old code passed a generator object where httpx expected a file-like; real httpx calls `.read(n)` on it, so the upload 502'd with `AttributeError: 'generator' object has no attribute 'read'`. Now passes the raw file handle (httpx uses `peek_filelike_length` → `fileno()` → `fstat()` to derive `Content-Length`, which also fixes a separate `httpcore.ReadError` from PVE rejecting chunked bodies). Plus PVE 9 schema fixes uncovered along the way: `_create_qemu_vm` made `bridge` optional (the hard-coded `net0=virtio,bridge=vmbr0` 403'd on SDN-managed PVE because the token lacks `SDN.Use`); `_import_disk` switched from `POST /qemu/{vmid}/importdisk` (PVE 9 returns 501) to `POST /qemu/{vmid}/config` with `scsi0={target}:0,import-from={volid}`; `clone_vm` split into `clone.post` (name/newid only) + `config.post` (cores/memory/sockets) + `resize.put` (disk, the new PVE 9 endpoint is `PUT /qemu/{vmid}/resize` with `disk=scsi0&size=+XG`); runner sanitizes underscores from `asset.role` (PVE 9 enforces strict DNS-1123 on the clone name); upload field renamed `content` → `filename` and added `?content=import` query param (PVE 9 needs both — `content` is the storage content-type filter, not the file field). Plus docs fixes: `PVEStorageAdmin` was a typo — the built-in role is `PVEDatastoreAdmin`; PVE 9 expects `--roles` (plural), not `--role`. Updated wizard HTML, `SETUP-UI.md`, `LIVE-DRILL-RUNBOOK.md`, and the admin service docstring. **Run #11** completed with `status=succeeded`, `pve_vmid=109`, audit log has all three events, asset teardown transitioned to `stopped`. Flipped L1 1.2–1.9 to ✅. **L1 ledger: 9 ✅ / 0 ❌ / 0 ⚠️**. Tests 275 → 276 (+1 regression test). |



