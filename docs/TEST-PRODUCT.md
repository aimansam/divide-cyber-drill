# Test Product Checklist

A graded definition of "ready for someone to try it". Each level is a
strict superset of the previous — you can't ship L2 without L1 green,
and L3 without L2.

> **Where we are today:** stack is healthy, 276 tests passing
> (was 275, +1 regression test for the upload-qcow2 fix). `make preflight`
> is 9/9 after the `/access/permissions` ACL fix **and** the
> `tpl-debian-cloudinit` template was created (run #11 completed with
> status `succeeded`).
>
> L1: **9 ✅ / 0 ❌ / 0 ⚠️** as of run #11. Items 1.3–1.9 all flipped
> from blocked → done in one operator-side upload + one ACL grant.
>
> L2 has auth wired (`X-Divide-Token` HMAC tokens, `divide issue-token`
> CLI, `started_by`/`actor` attribution), but **the rate limit, drill
> timeout, telemetry-sink, after-action JSON work hasn't started yet**.
> L2 requires ~3 h more before it's shippable.
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
| 2.7  | Rate limit on `POST /api/v1/drills` (max 5 in-flight per token) | ❌ no limit |
| 2.8  | Drill that runs > 30 min auto-cancels (prevents forgotten VMs racking up CPU bills) | ❌ no timeout |
| 2.9  | Audit log writes include the token subject (not just IP) | ⚠️  now requires handler-side work: router has the token, but the audit hook in `Runner._audit()` doesn't read it. Out of scope for the current item. |
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

> **L1 is closed** (run #11 succeeded, ledger 9/9 ✅). Items #1–#4 below
> shipped during the L1-closure round. Only #5 remains, and it's now
> optional — the wizard's `pveum` copy-paste block already walks an
> operator through the one-time `PVEDatastoreAdmin` grant without
> needing wizard automation.

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | **Cancel-path smoke tests** | ✅ done (`tests/test_cancel_smoke.py`) | flipped L1 1.10, 1.11, 1.12 |
| 2 | **`make verify` alias + CI wiring** | ✅ done (commit `be36033`) | flipped L2 2.13, 2.14 |
| 3 | **`/portal/test/` smoke in CI** | ✅ done (`tests/test_portal_smoke.py`, 6 tests) | static-analysis regex on the HTML; no browser needed |
| 4 | **Token middleware + `divide issue-token` CLI** | ✅ done (`app/core/auth.py`, `tools/issue_token.py`) | flipped L2 2.3, 2.4, 2.5 |
| 5 | **SSH-key wizard step** (Bucket E) so wizard flips `PVEDatastoreAdmin` itself | ❌ **next** (~1 h, optional) | removes the last remaining human action in a fresh deploy; the wizard's copy-paste block is the current stand-in |

### Where the L2 work sits

The remaining ~2.5 h to ship L2 is **not** in this table — it's in
[§L2](#l2--trusted-colleague-lan-demo). Items 2.7 (rate-limit),
2.8 (drill timeout), 2.11 (MinIO telemetry), 2.12 (after-action JSON)
are queued next. Once those four ship: L2 ledger 15/18 ✅,
tag `v0.2.0-l2`.

### Why we are NOT doing these next

- More PVE integration (multi-node, SDN zones, etc.) — that's L3
  scope per Phase 2 of PLAN.md.
- Real authn/authz (Keycloak/OIDC) — L3 (criteria 3.1–3.5).
- Resilient queue workers — Phase 3+ (criteria 3.8–3.13).
- PDF after-action reports — L2 item 2.12, rolled into the L2 block
  above (slots naturally with the MinIO work).

### Tracking these in the L1/L2 ledger

- #1 → L1 1.10, 1.11, 1.12.
- #2 → L2 2.13, 2.14.
- #4 → L2 2.3, 2.4, 2.5 (2.9 partially — full audit attribution
  needs the runner's `_audit()` hook updated to read the token subject).
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

| 2026-08-23 | feat(tests): portal static-analysis smoke (`tests/test_portal_smoke.py`, 6 tests). Asserts every API path fragment the wizard + test UI JS references exists in the FastAPI OpenAPI schema. Catches "JS calls a path that doesn't exist on the API" without a browser. Why not Playwright: would add ~150 MB CI image for the same failure-mode coverage. Tests 250 → 256 (+6). |
| 2026-08-23 | feat(auth): token middleware + CLI (`app/core/auth.py`, `tools/issue_token.py`, 19 tests). HMAC-SHA256 signed compact tokens carried in `X-Divide-Token`. `current_token` returns `TokenData | None` (None = anonymous); `require_token` 401s anonymous. CLI parses `--ttl` with `s/m/h/d` suffix + bare seconds. Secret resolution: explicit `DIVIDE_TOKEN_SECRET` > derived from `PROXMOX_TOKEN_SECRET` (dev) > per-process random fallback (with warning). Token subject is now recorded in `runs.started_by` and `runs.cancel.actor`. Flipped L2 2.3 / 2.4 / 2.5 → ✅. (2.9 — audit attribution from the token — needs the runner's `_audit()` hook updated; out of scope for this item.) Tests 256 → 275 (+19). |
| 2026-08-23 | fix(upload): `httpx` upload-qcow2 generator → file handle. The old code passed a generator object where httpx expected a file-like; real httpx calls `.read(n)` on it, so the upload 502'd with `AttributeError: 'generator' object has no attribute 'read'`. Now passes the raw file handle (httpx uses `peek_filelike_length` → `fileno()` → `fstat()` to derive `Content-Length`, which also fixes a separate `httpcore.ReadError` from PVE rejecting chunked bodies). Plus PVE 9 schema fixes uncovered along the way: `_create_qemu_vm` made `bridge` optional (the hard-coded `net0=virtio,bridge=vmbr0` 403'd on SDN-managed PVE because the token lacks `SDN.Use`); `_import_disk` switched from `POST /qemu/{vmid}/importdisk` (PVE 9 returns 501) to `POST /qemu/{vmid}/config` with `scsi0={target}:0,import-from={volid}`; `clone_vm` split into `clone.post` (name/newid only) + `config.post` (cores/memory/sockets) + `resize.put` (disk, the new PVE 9 endpoint is `PUT /qemu/{vmid}/resize` with `disk=scsi0&size=+XG`); runner sanitizes underscores from `asset.role` (PVE 9 enforces strict DNS-1123 on the clone name); upload field renamed `content` → `filename` and added `?content=import` query param (PVE 9 needs both — `content` is the storage content-type filter, not the file field). Plus docs fixes: `PVEStorageAdmin` was a typo — the built-in role is `PVEDatastoreAdmin`; PVE 9 expects `--roles` (plural), not `--role`. Updated wizard HTML, `SETUP-UI.md`, `LIVE-DRILL-RUNBOOK.md`, and the admin service docstring. **Run #11** completed with `status=succeeded`, `pve_vmid=109`, audit log has all three events, asset teardown transitioned to `stopped`. Flipped L1 1.2–1.9 to ✅. **L1 ledger: 9 ✅ / 0 ❌ / 0 ⚠️**. Tests 275 → 276 (+1 regression test). |



