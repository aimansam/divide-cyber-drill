# User Requirements

A breakdown of who uses div:ide, what each role needs to do, and what
is wired today vs. what is deferred to a later level. Companion to:

- [`PLAN.md`](PLAN.md) — design + architecture
- [`TEST-PRODUCT.md`](TEST-PRODUCT.md) — done-definition per level (L1/L2/L3)
- [`LIVE-DRILL-RUNBOOK.md`](LIVE-DRILL-RUNBOOK.md) — operator procedure for one drill

> **Status:** §15 cyber-range plans **ALL CLOSED**. Every role's
> section below now lists what the platform can do today (post-F8).
> The §15 follow-ons (R1-R7 in PLAN.md §17) are the only remaining
> work; they're tracked there, not duplicated here.
>
> **Tests:** 431 root + 428 API = 859 passing (3 pre-existing
> unrelated CLI auth failures).

> **Scope of this doc.** "User requirement" means a capability that a
> real person needs in order to do their job with the platform. It is
> **not** a feature roadmap (those items live in
> [`TEST-PRODUCT.md`](TEST-PRODUCT.md) §L1/L2/L3) and **not** an
> implementation plan (that's [`PLAN.md`](PLAN.md)). This doc maps the
> space between: *who is the user, what can they do today, what's
> missing*.

---

## 1. Personas

The platform serves five human roles and one internal "watchdog"
actor. **None of the role-based gates are enforced yet** — the `role`
field on a token is a free-form string and `app/core/auth.py` §"What
auth does NOT do" explicitly defers RBAC to a later level — but the
personas are well-defined and the token layer is ready to carry the
value.

### Role summary

| Persona | What they're trying to do | Token `role` (today) |
|---|---|---|
| Platform Admin / Operator | Stand up the platform; keep it healthy; deploy new templates; answer "is PVE OK?" | `admin` |
| Drill Lead / Instructor | Author scenarios, run drills for a cohort, debrief | `lead` |
| Red Team Participant | Attack the cloned target VMs | `red` |
| Blue Team Participant | Detect + respond; see telemetry | `blue` |
| Observer / Reviewer | Read-only: see runs, audit, reports | `observer` |
| Watchdog (system) | Auto-cancel drills that exceeded their `timeout_min` | n/a (internal) |

### Persona 1 — Platform Admin / Operator

**Goal:** keep the platform healthy; deploy templates; answer "is
PVE OK?".

**Wired today (L2):**
- HMAC token with `role=admin` (`tools/issue_token.py --role admin`).
- HMAC secret resolution order: `DIVIDE_TOKEN_SECRET` > derived from
  `PROXMOX_TOKEN_SECRET` (dev) > per-process random fallback.
- Can call all `/api/v1/admin/*` endpoints: probe, upload-qcow2,
  create-template, set-template, drill-template-status,
  start-first-drill, storage. **Gated by `require_role(ADMIN)`**
  at the router level since commit `0c2da49` — anonymous probes
  return 401, not the full PVE topology.
- Drill-start / cancel / per-asset audit rows attributed to
  `token.sub` (commit `359a62d`).
- [`/portal/`](../services/portal/index.html) setup wizard for the
  one-time deploy.
- [`/`](../services/portal/app/index.html) user portal
  (commits `d0ce912`, `M3.2-Half1`, `M3.2-Half2`) — operators see
  `ScenariosCard` + `PveOpsCard` (read-only PVE health + storage +
  drill-template-status) + `ScenarioAuthoringCard` (import /
  archive / restore scenario YAML) + `MyRunsCard` ("All runs") +
  `RunLifecycleCard` (start + refresh + cancel any drill) +
  `RunInspectorCard` (full run detail) + `AssetsCard` (copy-to-
  clipboard SSH targets) + `AuditExplorerCard` (append-only audit
  timeline) plus the server-verified `useMe()` identity badge. **The
  full admin composition is now live**; what remains is half-finished
  UX polish (the wizard stays the deploy surface; PveOpsCard's
  future upload-QCOW2 / create-template flow doesn't replace it).

**Needs not yet met:**
- `require_role("admin")` gate on `/api/v1/admin/*` — today **any
  caller, including unauthenticated**, can hit `/probe` and probe
  PVE reachability. Explicitly deferred by `app/core/auth.py`.
- A "what did the admin do this week?" audit query surface — needs
  role-filtered audit listing.
- Wizard step 5 / Bucket E (`pveum`-grant automation via `asyncssh`)
  is optional polish (next-plan #8).

### Persona 2 — Drill Lead / Instructor

**Goal:** author scenarios, schedule + run drills, debrief the cohort.

**Wired today (L2):**
- HMAC token with `role=lead`.
- `GET /api/v1/scenarios` (list + detail) — the lead's authoring
  surface today is YAML in `examples/scenarios/`, pulled into the DB
  by the `ScenarioSync` job.
- `POST /api/v1/drills` (will be rate-limited, next-plan #3).
- `POST /api/v1/drills/{id}/cancel` with `reason` + `actor` body.
- `GET /api/v1/drills/{id}` + `/audit` for live run inspection.
- `/portal/test/` cards 1
  (scenario picker), 2 (run lifecycle), 3 (cancel), 5 (audit log).
- [`/`](../services/portal/app/index.html) (commits
  `d0ce912`, `M3.2-Half1`, `M3.2-Half2`) — the lead's primary
  day-2 surface: `TokenBar` + `ScenariosCard` + `ScenarioAuthoringCard`
  (import / archive / restore) + `MyRunsCard` ("All runs") +
  `RunLifecycleCard` (start + refresh + cancel any drill) +
  `RunInspectorCard` (full detail) + `AssetsCard` (SSH targets) +
  `AuditExplorerCard` (timeline). **The full lead composition is
  now live.** The lead does NOT get `PveOpsCard` (PVE-health is
  admin-only). This is the page that replaces `/portal/test/`
  for day-2 use; `/portal/test/` still ships as the operator's
  diagnostic tool.

**Needs not yet met:**
- Full scenario authoring CRUD UI in the portal — Half 2's
  `ScenarioAuthoringCard` ships the import + archive + restore
  halves. Edit / metadata-rename / versioned-archive UI is its
  own follow-up (criterion 3.12).
- After-action JSON report (`GET /api/v1/drills/{id}/report`,
  next-plan #6) for debrief — most data is in the DB already; one
  Prometheus query away.
- "Drills led by me" filter in audit UI.

### Persona 3 — Red Team Participant

**Goal:** attack the cloned target VMs.

**Wired today (L2):**
- HMAC token with `role=red`.
- `POST /api/v1/drills` (rate-limited, per-token, next-plan #3).
- `GET /api/v1/drills/{id}` for the run they started.
- `GET /api/v1/drills/{id}/audit` for self-attribution.
- `/portal/test/` cards 2 (run lifecycle), 4 (assets).
- [`/`](../services/portal/app/index.html) (commits
  `d0ce912`, `M3.2-Half1`, `M3.2-Half2`) — the **trainee-facing
  surface**. Full red composition: `ScenariosCard` + `MyRunsCard`
  ("My runs", server-filtered to own by `visible_runs_query` from
  `4d840f9`) + `RunLifecycleCard` (start + refresh + cancel own
  only — the cancel button disables with a tooltip mirroring the
  server 403) + `RunInspectorCard` (full detail) + `AssetsCard`
  (SSH targets for the cloned VMs) + `AuditExplorerCard`
  (timeline). Red does NOT get `PveOpsCard`, `ScenarioAuthoringCard`,
  or other operators' runs.

**Needs not yet met:**
- **Browser console to the cloned VM.** [`PLAN.md`](PLAN.md) §7 calls
  for `noVNC + Apache Guacamole in Docker` for trainees — Phase 2+,
  not yet. **This is the biggest single UX gap for trainees today:**
  they can `POST /drills` and see `pve_vmid=109` in the response, but
  they cannot open a browser window and start typing in the VM. Until
  noVNC lands, a "drill" is "watch the run-detail card update every
  2 s".
- "Own runs only" filter on read endpoints — today any token can
  `GET /drills/{id}` for any run id. Fine for L2 single-tenant; a
  multi-tenant P0 in L3 (criterion 3.12).
- A token-per-drill-session CLI helper — `divide issue-token --user
  alice-red --role red --ttl 2h` works, but the trainee needs to know
  to mint one.

### Persona 4 — Blue Team Participant

**Goal:** detect + respond; see telemetry from inside the cloned
victim VMs.

**Wired today (L2 + F8 SOC view):**
- HMAC token with `role=blue`.
- `GET /api/v1/drills/{id}` for the run they joined.
- `GET /api/v1/drills/{id}/audit` for self-attribution.
- **F8 — Live SOC view:** blue subscribes to the live event
  stream via SSE (`GET /api/v1/runs/{id}/events/stream`). They see
  `run.started` + `asset.running` + `flag.captured` + admin/lead
  injected `kill-chain.signal` events in real time. Portal
  `SocViewCard` shows the timeline with severity filter (info /
  low / medium / high), pause/resume, and reconnect handling.
- `/portal/test/` cards 4 (assets), 5 (audit), 6 (metrics).
- [`/`](../services/portal/app/index.html) (commits
  `d0ce912`, `M3.2-Half1`, `M3.2-Half2`) — the blue team's
  primary surface. Full blue composition (read-only): `ScenariosCard`
  + `MyRunsCard` ("My runs" — own-runs filter on the server) +
  `RunInspectorCard` (full detail) + `AssetsCard` (SSH targets
  for the cloned VMs) + `AuditExplorerCard` (timeline). Blue does
  NOT get `RunLifecycleCard`, `PveOpsCard`, or `ScenarioAuthoringCard`
  — every card that has a write button is hidden. Blue clicks on a
  "Run" in `MyRunsCard` and gets the same detail + assets + audit
  that red sees, minus the Start / Cancel buttons.
- Grafana at `localhost:3000` (admin/`divide`) — but **no anonymous
  viewer** (L2 2.6 ⚠️, deferred). The blue team needs to be given the
  admin creds or we ship the `grafana.ini` overlay (~30 min).

**Needs not yet met:**
- **Wazuh + MISP events forwarded from inside the guest VM**
  (criteria L3 3.7 / 3.8). F8 ships the *event-bus* path: runner
  emits `run.*` / `asset.*` / `flag.captured` events and the SOC
  view streams them via SSE. The remaining gap is the
  Wazuh/MISP-specific sink adapter that takes the in-process
  EventBus and forwards to a real SOC stack — deferred to F8.5 / G11.
- **Cross-team flag capture:** F5 + F6 give blue a `submit-flag`
  endpoint scoped to their team; flag scores roll up into the
  exercise's leaderboard (F6 `LeaderboardCard`).
- **Cloud-init user-data applied to the cloned VM** so the guest
  actually has an SSH key + hostname out of the box (next-plan #7).
  Without this, even *if* Wazuh were wired, the guest can't enroll.
- **Grafana dashboards provisioned** (currently the admin must add
  Prometheus as a data source manually).

### Persona 5 — Observer / Reviewer

**Goal:** read-only: see runs, audit, reports. Cannot start or
cancel. Examples: compliance auditor, customer-demonstration guest,
after-the-fact reviewer.

**Wired today (L2):**
- HMAC token with `role=observer` (free-form string).
- Same read access as red/blue: `GET /drills/{id}`, `/audit`,
  `/metrics`, future `/report`.
- `/portal/test/` cards 5 (audit), 6 (metrics).
- [`/`](../services/portal/app/index.html) (commits
  `d0ce912`, `M3.2-Half1`, `M3.2-Half2`) — the observer's
  surface (read-only). Full observer composition: `ScenariosCard`
  + `MyRunsCard` (rendered as "All runs" — observer sees every run
  in the system) + `RunInspectorCard` (full detail) +
  `AuditExplorerCard` (timeline). Observer does NOT get
  `RunLifecycleCard`, `PveOpsCard`, `ScenarioAuthoringCard`, or
  `AssetsCard` (asset detail is operator-facing; the inspector
  surfaces the asset summary inline). Server-side, observer tokens
  are gated by `require_role(OBSERVER, ...)` on every read endpoint
  (commit `4d840f9`).
- **F8 — Observer SOC view:** observers can subscribe to live
  event streams for any run. Use case: compliance auditor watches
  a live red-vs-blue drill without operator involvement.

**Needs not yet met:**
- **No read-only API surface.** Every endpoint either writes
  (`POST /drills`, `/cancel`) or has both read+write semantics. To
  support an observer role properly we need either:
  - A `require_role(...)` gate on writes (block observer from
    `POST`), or
  - A "view-only" mode on `/portal/test/` that hides the "Start
    drill" and "Cancel" buttons.
- **"Audit of the observer's reads"** — compliance wants to know who
  looked at what. Deferred to L3.
- Anonymous Grafana viewer (same gap as blue team — L2 2.6 ⚠️).

### Persona 6 — Watchdog (system)

**Goal:** auto-cancel drills that exceeded their
`scenario.duration_min + 30s` grace, so forgotten VMs don't rack up
CPU bills.

**Wired today:** nothing.

**To be wired (next-plan #4, ~45 min):**
- Background task on `Runner.start_run` that schedules a cancel.
- On trigger: calls `cancel_run(reason="auto-timeout",
  actor="watchdog")` + writes a new `RUN_TIMEOUT` audit row.
- The 2.9 actor work already shipped (`Runner._audit()` threads
  `actor=` through), so `actor="watchdog"` lands cleanly.

---
Plus a deployment-time persona — "the operator who first installs the
platform" — who only needs the setup wizard and does not need a
long-lived token.

---

## 2. Per-role permission matrix (L2 target)

This is the **enforced** permission set as of L2 2.9 (commits
`1631448`, `0c2da49`, and the matrix commit that followed). All
gates below are real and exercised by the parametrized matrix in
`services/api/tests/test_authorization.py`.

| Endpoint | admin | lead | red | blue | observer | anon |
|---|---|---|---|---|---|---|
| `GET /api/v1/scenarios` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /api/v1/drills` | ✅ | ✅ | ✅ (rate-limited) | ❌ | ❌ | ❌ |
| `GET /api/v1/drills/{id}` | ✅ any | ✅ any | ✅ own | ✅ own | ✅ any | ❌ |
| `POST /api/v1/drills/{id}/cancel` | ✅ | ✅ | ✅ own | ❌ | ❌ | ❌ |
| `GET /api/v1/drills/{id}/audit` | ✅ | ✅ | ✅ own | ✅ own | ✅ | ❌ |
| `GET /api/v1/drills/{id}/report` *(next-plan #6)* | ✅ | ✅ | ✅ own | ✅ own | ✅ | ❌ |
| `/api/v1/proxmox/*` *(until M5 lands)* | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/api/v1/admin/*` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `GET /metrics` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `GET /portal/` (wizard) | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `GET /portal/test/` (operator tool) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `GET /` (user portal) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Legend:** ✅ own = result is filtered to `runs.started_by =
token.sub`. ✅ any = full list / all rows. ❌ = 403. The
`/api/v1/proxmox/*` row is intentionally "all ✅" for now — the
wizard's load-on-page-load pattern calls `/proxmox/health` from
the operator's browser before any token has been minted. M5 in the
post-L1 plan owns the full `/proxmox/*` hardening pass (the
intended per-endpoint gating is documented in the
`routers/proxmox.py` module docstring).

The portal URLs are static HTML and don't authenticate; gating is
purely about what the JS calls (X-Divide-Token). The user portal at
`/` is the canonical entry point for trainees and leads;
the operator tool at `/portal/test/` is what the operator uses
during setup, troubleshooting, and ad-hoc poking. Both are
read-accessible to anyone on the LAN — RBAC is enforced only at the
API layer.

**Drill cancel own-only filter for red** is the headline security
control: `routers/drills.py::cancel_drill` checks
`run.started_by != token.sub` for red tokens and returns 403 (not
404) before invoking the runner. The check is exercised both by
the parametrized matrix (`403` cells) and the static code-shape
test (`test_cancel_endpoint_has_red_own_only_check_in_code`).

---

## 3. Cross-cutting gaps (apply to all roles)

These items don't belong to a single persona but block the multi-user
L2 demo.

| Gap | Affects | Severity | Plan slot |
|---|---|---|---|
| ~~No `require_role(...)` gate on any router~~ | everyone | **CLOSED** L2 2.9 (commits `1631448`, `0c2da49`, matrix commit). All routers now enforce the §2 matrix; see `services/api/tests/test_authorization.py`. | done |
| `/portal/test/` UI doesn't accept `X-Divide-Token` | operator | cosmetic — `/` does (commit `d0ce912`) | ~30 min to retrofit; the user portal replaces `/portal/test/` once M3 lands |
| No browser console to the cloned VM (noVNC) | red, blue | **biggest single UX gap** | Phase 2 / L3 |
| No guest-side telemetry from inside the VM | blue, audit | drill has no observable "moving target" | L3 3.8; gated on next-plan #7 (cloud-init user-data) |
| No Grafana anonymous viewer (L2 2.6 ⚠️) | blue, observer | can't share a dashboard with a non-admin | ~30 min; deferred per next plan |
| No CORS allowlist from `DIVIDE_DOMAIN` (L2 2.10 ⚠️) | red, blue (remote) | browser on a different origin fails | next-plan #2 (20 min) |
| No rate-limit on `POST /api/v1/drills` (L2 2.7 ⚠️) | admin (protect), red (protect) | cost risk if a misclick spawns 50 VMs | next-plan #3 (45 min) |
| No "own runs only" filter | everyone | **CLOSED** L2 2.9. `app/services/authorization.py::visible_runs_query` + `can_view_run` apply `WHERE runs.started_by = token.sub` for red/blue tokens on `GET /drills`, `GET /drills/{id}`, and `GET /drills/{id}/audit`. | done |
| No token secret rotation / revocation | everyone | leaked token valid until `exp` | L3 — token-bucket rejected list keyed by `sub` |
| No drill auto-timeout (L2 2.8 ⚠️) | admin, watchdog | forgotten drills rack up CPU | next-plan #4 (45 min) |
| No MinIO telemetry sink (L2 2.11 ⚠️) | lead, blue | audit events don't reach `divide-artifacts` | next-plan #5 (1 h) |
| No after-action JSON report (L2 2.12 ⚠️) | lead, observer | debrief = re-query the DB by hand | next-plan #6 (45 min) |
| No role-aware UI composition in `/` | red, blue, observer, lead, admin | **CLOSED** commits `M3.2-Half1` + `M3.2-Half2`. `COMPOSITIONS` in `src/app.tsx` renders only the cards each role can use; `tests/test_portal_app_role_composition.py` pins the per-role card set (6 parametrized cases + per-card role documentation + bundle integrity). Identity badge is server-verified via `GET /api/v1/me` + `useMe()` — no more client-side JWT decode. Half 2 closed the rest: `RunInspectorCard`, `AssetsCard`, `AuditExplorerCard`, `PveOpsCard` (admin), `ScenarioAuthoringCard` (admin + lead). | done |

---

## 4. Open questions

1. **Multi-user demo this week?** If yes, we need to add a 9th item
   to the next plan: token-aware `/portal/test/` + `require_role` on
   `/api/v1/admin/*` (~1 h, ships ahead of #2). **Update 2026-08-24:**
   the user portal at `/` now handles tokens end-to-end
   (commit `d0ce912`). **Update 2026-08-24 (later):** the
   `require_role(...)` substrate + `/admin/*` gate + drill matrix +
   own-runs-only filter all shipped in commits `1631448` / `0c2da49`
   / matrix commit. The multi-user demo path is fully wired:
   `/` for the UI, `/api/v1/*` for the API, both behind
   the §2 matrix.
2. **Compliance / observer read-only needed?** If yes, add items 9 +
   10: observer role + filtered audit read endpoints (~1.5 h, L3 work
   done early).
3. **Token TTL defaults per role?** `tools/issue_token.py --ttl` is
   free-form. Sensible defaults:
   - `admin` — 7 d
   - `lead` — 4 h
   - `red`, `blue` — 2 h (one drill session)
   - `observer` — 30 d
4. **Per-drill short-lived token?** Should `POST /drills` *issue* a
   token the caller can use to read the just-created run? Today the
   caller's token already has `sub` and they can read; but if a
   trainee hands their long-lived token to the API, that's a leak.
   L3 polish.

---

## 5. See also

- [`TEST-PRODUCT.md`](TEST-PRODUCT.md) §L2 — the L2 ledger this doc
  describes the persona-side view of.
- [`PLAN.md`](PLAN.md) §1 — vision statement ("lets a blue team, red
  team, or training cohort…").
- [`PLAN.md`](PLAN.md) §7 — `noVNC + Guacamole` plan for trainee
  console access (the L3 answer to Persona 3 / 4's biggest gap).

  `/portal/test/`.
- [`PORTAL-APP.md`](PORTAL-APP.md) — the React/Vite user portal at
  `/`.
- [`SETUP-UI.md`](SETUP-UI.md) — the setup wizard at `/portal/`.