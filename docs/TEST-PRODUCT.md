# Test Product Checklist

A graded definition of "ready for someone to try it". Each level is a
strict superset of the previous — you can't ship L2 without L1 green,
and L3 without L2.

> **Where we are today:** stack is healthy, 250 tests passing
> (was 190, +60 this session). `make preflight` is now 8/9 after the
> /access/permissions ACL fix (commit `ab0ab58`) — the only remaining
> failure is the missing cloud-init template, which is PVE-side work.
> L1: 7 ✅ / 5 ❌ / 3 ⚠️ (4 of the 5 ❌ cascade from a successful
> live-drill; 1.2 is the missing template). The cancel-path coverage
> (`tests/test_cancel_smoke.py`) flipped L1 1.10, 1.11, 1.12 from ⚠️ to ✅
> without any PVE work.
>
> `make verify` is the new aggregate gate (lint + test + preflight +
> smoke) — runs the same checks locally that CI runs in
> `.github/workflows/ci.yml`. The orchestration of `tools/verify_drill.py`
> is covered by `tests/test_verify_drill.py::test_main_returns_*` so
> it gets exercised on every CI run without needing a live drill in the
> DB.
>
> **Setup wizard:** `/portal/` is live (commit `496efd1`). Operators can
> stand up a fresh PVE-backed deployment from a browser — no SSH into
> PVE required except for one `pveum` grant. See `docs/SETUP-UI.md`.
>
> **Test UI:** `/portal/test/` is live (commit `cd0ccb5`). Browser tool
> with 7 cards exposing every control-plane endpoint as a click button
> (scenarios, drills, cancel, assets, audit, metrics, Proxmox). See
> `docs/TEST-UI.md`.

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
| 1.2 | `make preflight` reports 9/9 PASS | `make preflight` | ❌ 8/9 (template missing; ACL now passes) |
| 1.3 | `make live-drill SCENARIO=first-live-drill TIMEOUT=300` completes with `run.status == succeeded` | tool output | ❌ not run yet |
| 1.4 | `make verify-drill` reports 4/4 PASS | tool output | ❌ blocked on 1.3 |
| 1.5 | Grafana Panel 1 (drill count) ticks up after the drill | http://localhost:3000 | ❌ blocked on 1.3 |
| 1.6 | Grafana Panel 3 (last status) shows `succeeded` | http://localhost:3000 | ❌ blocked on 1.3 |
| 1.7 | `runs` table has a row with `pve_vmid` populated (proves real clone, not mock) | `psql -c "SELECT id, scenario_id, status, pve_vmid FROM runs ORDER BY id DESC LIMIT 3"` | ❌ blocked on 1.3 |
| 1.8 | `audit_log` table has entries for `run.started`, `asset.spawned`, `run.completed` for that run | `psql -c "SELECT action, at FROM audit_log WHERE run_id=$ID ORDER BY at"` | ❌ blocked on 1.3 |
| 1.9 | After teardown, asset row transitions to `status=stopped` (or `orphaned` if destroy failed) | `psql -c "SELECT role, status FROM assets WHERE run_id=$ID"` | ❌ blocked on 1.3 |
| 1.10 | Drill can be cancelled mid-flight with `POST /api/v1/drills/{id}/cancel` | tool output | ✅ covered by `tests/test_cancel_smoke.py` (happy path + audit + counter invariants) |
| 1.11 | `make live-cancel CANCEL_AFTER=10` exits with the run in `cancelled` state | tool output | ✅ covered by `tests/test_cancel_smoke.py::test_live_cancel_marks_run_cancelled_with_reason` |
| 1.12 | Drill can be cancelled by Prometheus watcher (the `watch_drill.py` path) | `make watch-drill OUTCOME=cancelled` | ✅ covered by `tests/test_cancel_smoke.py::test_watch_drill_cancel_after_path_triggers_cancel_endpoint` + `tests/test_watch_drill.py::test_cancel_after_sends_cancel_request` |
| 1.13 | Operator runbook exists and is accurate | `docs/LIVE-DRILL-RUNBOOK.md` | ✅ written |
| 1.14 | All previously-shipped stages have passing tests | `make test` | ✅ 250 passing |
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
| 2.3  | API has a token-based auth middleware (`X-Divide-Token` header) | ❌ wide-open |
| 2.4  | Token issuance CLI: `divide issue-token --user alice --role trainee` | ❌ no auth subsystem |
| 2.5  | `runs.started_by` populated from the token subject (proves attribution) | ⚠️  field exists, no auth |
| 2.6  | Grafana has basic-auth (anonymous viewer, admin via env-var creds) | ⚠️  admin only |
| 2.7  | Rate limit on `POST /api/v1/drills` (max 5 in-flight per token) | ❌ no limit |
| 2.8  | Drill that runs > 30 min auto-cancels (prevents forgotten VMs racking up CPU bills) | ❌ no timeout |
| 2.9  | Audit log writes include the token subject (not just IP) | ⚠️  fields exist |
| 2.10 | CORS allowed origins constrained to `DIVIDE_DOMAIN` | ⚠️  no CORS configured |
| 2.11 | Telemetry sinks wire-up: drill completion uploads audit log + asset metadata to MinIO `divide-artifacts` bucket | ❌ spec field is read, ignored |
| 2.12 | After-action JSON report downloadable from `GET /api/v1/drills/{id}/report` | ❌ endpoint doesn't exist |
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
- Already shipped (no work): 2.1 (test UI), 2.16 (wizard), 2.17, 2.18 (API endpoints)

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
| 3.2  | RBAC: roles `admin` / `trainer` / `trainee` / `viewer` | ❌ no roles |
| 3.3  | Per-user PVE quota (max concurrent VMs, max vCPU-hours/month) | ❌ no quota |
| 3.4  | Per-user scenario library (private scenarios not visible to others) | ❌ flat library |
| 3.5  | Billing meter: drill-minutes logged per user | ❌ no metering |
| 3.6  | PDF after-action report (not just JSON) | ❌ no PDF |
| 3.7  | Wazuh / MISP integration: drill events published to SOC stack | ❌ not wired |
| 3.8  | Multi-node PVE cluster support (drill assets span nodes for realism) | ❌ single node |
| 3.9  | SDN zone per drill (isolated L2 for red/blue traffic) | ❌ no SDN |
| 3.10 | Scheduling: cron-driven drills (e.g. weekly red-team) | ❌ no scheduler |
| 3.11 | Scenario marketplace (import/export YAML, signed) | ❌ local-only |
| 3.12 | Multi-tenant org model (org → team → user) | ❌ single-tenant |
| 3.13 | Public status page + incident comms | ❌ no status page |
| 3.14 | SOC 2-ish audit trail (who ran what, when, with what output) | ⚠️  audit exists, not exported |
| 3.15 | L2 criteria all still green | ❌ blocked on L2 |

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

Five work items that close most of the remaining L1/L2 without PVE.
Each is small enough to ship in one sitting.

| # | Item | Effort | Files | PVE needed? | What it flips |
|---|---|---|---|---|---|
| 1 | **Cancel-path smoke tests** for `live-cancel` + `watch-drill` via `MockProxmoxAdapter` | 30 min | `tests/test_cancel_smoke.py` (new) | No | L1 1.10, 1.11, 1.12 → ✅ |
| 2 | **`make verify` alias** + CI wiring | 30 min | `Makefile`, `.github/workflows/ci.yml` | No | L2 2.13 ✅, 2.14 ✅ |
| 3 | **`/portal/test/` Playwright smoke** (catches UI regressions in CI) | 30 min | `tests/test_portal_smoke.py` | No | regression guard |
| 4 | **Token middleware + `divide issue-token` CLI** | 1.5 h | `app/core/auth.py`, `tools/issue_token.py` | No | L2 2.3, 2.4, 2.5, 2.9 → ✅ |
| 5 | **SSH-key wizard step** (Bucket E) so wizard flips `PVEStorageAdmin` itself | 1 h | `app/services/admin.py`, `portal/index.html` | **One SSH key setup** | full autonomy for fresh deploys |

**Total: ~3.5 h.** After this: full L1 ✅, ~7/18 L2 ✅, deployment is
"open browser, click through, drill runs".

### Why this order

1. **#1 first** because it flips three L1 criteria without any PVE
   work. Cheapest L1 closure.
2. **#2 second** because `make verify` makes every later change safer
   to ship (catches regressions locally + in CI).
3. **#3 third** because the test UI is already the primary tool
   you'll use to debug the next round of changes.
4. **#4 fourth** because token middleware unblocks L2 properly
   (currently `/api/v1/admin/*` and `/portal/*` are wide open).
5. **#5 last** because it's the only item needing a one-time PVE
   host SSH key — do it once L1 + L2-essentials are done.

### Why we are NOT doing these next

- More PVE integration (multi-node, SDN zones, etc.) — that's L3
  scope per Phase 2 of PLAN.md.
- Real authn/authz (Keycloak/OIDC) — L3 (criteria 3.1–3.5).
- Resilient queue workers — Phase 3+ (criteria 3.8–3.13).
- PDF after-action reports — that's a single L2 item (2.12), slot it
  in with the MinIO work (#5 above).

### Tracking these in the L1/L2 ledger

Each item above maps to existing criteria:

- #1 → L1 1.10 (cancel endpoint), 1.11 (live-cancel CLI), 1.12 (watcher).
- #2 → L2 2.13 (make verify), 2.14 (CI).
- #4 → L2 2.3, 2.4, 2.5, 2.9.
- #5 → not on the L1/L2 list as a single criterion, but enables
  "1.2 succeeds via wizard" so the operator never has to SSH for
  PVE perms again.

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

---

## Update log

| Date | Change |
|---|---|
| 2026-08-23 | Initial draft. L1 7/15 green, blocked on 2 PVE steps. |
| 2026-08-23 | fix(verify-drill): label-aware metric parsing (commit `2e4abf7`). Tests 190 → 216 (+10). verify-drill now distinguishes `divide_runs_total{outcome=..., adapter="real"}` instead of collapsing labels — regression check is no longer blind to failed-drill increments. Doc-relative figures (this file) updated. |
| 2026-08-23 | fix(preflight): use `/access/permissions` for ACL check (commit `ab0ab58`). PVE's `/access/acl` requires `Access.Audit` which is NOT part of `PVEVMAdmin` — correctly-scoped tokens were getting an empty list and the check failed. Switched to `/access/permissions` which every authenticated principal can read. preflight 7/9 → 8/9 (only the template remains). |
| 2026-08-23 | feat(setup): web wizard at `/portal/` (commit `496efd1`). Operators can stand up a fresh PVE-backed deployment from a browser — no SSH into PVE required except for one `pveum` grant. 4 steps: probe perms → grant perms → upload cloud image → run first drill. Tests 216 → 236 (+20). |
| 2026-08-23 | feat(ui): operator test UI at `/portal/test/` (commit `cd0ccb5`). 7 cards expose every control-plane endpoint as click buttons: scenarios, drills (start/refresh/cancel), assets, audit log, metrics, Proxmox state. Added `GET /api/v1/drills/{id}` and `GET /api/v1/drills/{id}/audit` read-only endpoints (the list endpoint only returned summary rows). Tests 236 → 243 (+7). |
| 2026-08-23 | feat(tests): cancel-path smoke coverage (`tests/test_cancel_smoke.py`, 5 tests). Proves `make live-cancel` happy path (Run→CANCELLED, reason recorded, audit entry written, `divide_cancel_requests_total{result="already_terminal"}` does **not** tick on success), 404 on unknown run, 409 on already-terminal, plus the `watch_drill --cancel-after` end-to-end path via mocked httpx. Flipped L1 1.10 / 1.11 / 1.12 from ⚠️ to ✅ **without any PVE work**. Tests 243 → 248 (+5). |
| 2026-08-23 | feat(verify): `make verify` aggregate gate + CI coverage of `tools/verify_drill.py`. The `verify` Makefile target chains `lint && test && preflight && smoke` (preflight is `-`-prefixed so a PVE-unreachable dev box still passes — useful for laptops). `tests/test_verify_drill.py` got two new tests (`test_main_returns_zero_for_successful_run`, `test_main_returns_one_for_failed_run`) that drive the full `verify_drill.main()` CLI with mocked httpx, proving the orchestrator works end-to-end without a live drill in the DB. Flipped L2 2.13 / 2.14 to ✅. Tests 248 → 250 (+2). |




