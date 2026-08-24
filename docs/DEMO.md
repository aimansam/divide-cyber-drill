# div:ide Demo — Show Off the Cyber Range in 5 Minutes

> **Status:** F4-UI demo runner shipped (commit `a76f4ee`).
> **Audience:** anyone demoing div:ide to a colleague, investor,
> customer, or trainer.

## TL;DR

```bash
# 1. Bring the stack up (skip if already running)
make up

# 2. Run the demo runner
make demo

# 3. Visit http://localhost:8000/portal/app/
#    Sign in with whatever bootstrap admin you set, or paste a token.
```

The runner tells you:
- Whether the API is reachable
- Whether the portal bundle is being served
- The list of scenarios in the catalog
- The 6 F4-UI tabs and what each shows
- The cyber-range identity scenarios (which one to start with)

## What you should see, in order

1. **Sign-in screen** — username + password fields (F3-prep UX). If
   no bootstrap admin was set, you'll see the setup wizard link for
   paste-your-token. Either path lands on the same portal.
2. **Dashboard** — KPI tiles. Empty state if no runs yet.
3. **Operate** — pick a scenario, click "Start drill". For the
   cyber-range demo, pick `red-vs-blue-baseline` (it has 6 assets
   across red/router/blue zones).
4. **Observe** (or follow the auto-redirect) — live drill console
   with `LIVE` pulse badge, duration timer, topology graph,
   asset table, audit feed. If the runner can't actually provision
   the VMs (F3 not shipped), the run will end in `failed` and you
   can still demo the topology + audit surfaces.
5. **Admin** (admin/lead only) — PVE health, scenario library,
   user list, range operator console.
6. **History** — past runs filterable by status (all / running /
   succeeded / failed / timeout / cancelled).
7. **Profile** — your runs scoped to your sub.

## Setup steps in detail

### One-time: bootstrap the first admin (optional but recommended)

Add to `deploy/.env`:

```bash
DIVIDE_BOOTSTRAP_ADMIN_SUB=alice
DIVIDE_BOOTSTRAP_ADMIN_PASSWORD=change-me-immediately
```

Then `make up` (or `make restart` to pick up the env change).

The API logs `divide_api.bootstrap_admin.created sub=alice` on
startup. After the admin exists, remove both env vars from
`.env` so the bootstrap is a no-op (and so the password isn't
visible in `docker compose config`).

### Demo the scenario catalog

`tools/demo.sh` lists every scenario the catalog returns. The
demo scenarios worth highlighting:

| Scenario | What it shows | Run-time reality |
|---|---|---|
| `red-vs-blue-baseline` | 6-asset red↔router↔blue topology graph | ✅ **F3 shipped** (`2a97525` + `6e9e5b5`). The runner iterates ``spec.networks[]`` and creates one bridge per declaration. The run actually executes end-to-end against real PVE **once the operator has set up the bridges per [`docs/F3-RUNBOOK.md`](F3-RUNBOOK.md)**. The mock-adapter path runs in CI/dev without PVE. |
| `first-live-drill` | Single-VM smoke | Works if PVE is configured |
| `phish-to-ransom` | Story-driven drill (good for narrating the demo) | Works if PVE is configured |
| `lateral-movement-baseline` | Blue team baseline | Works if PVE is configured |

If you only have PVE partially configured, pick `first-live-drill`
— it's the most forgiving.

### Demo a live drill

1. Operate tab → click the scenario card.
2. Click "Start drill".
3. The URL bar updates to `#/observe` automatically.
4. Watch the LIVE badge pulse. The topology graph populates as
   assets go PLANNED → CLONING → BOOTING → RUNNING.
5. After 30 seconds, click "Refresh" to see the audit feed
   accumulate events.
6. When the drill ends, click "Download report" — the JSON
   after-action report from `GET /api/v1/drills/{id}/report` is
   the canonical artifact.

### Demo the operator console (admin/lead only)

1. Admin tab → scroll to "Range operator console".
2. It lists every RUNNING/PENDING drill across the cyber range.
3. The "Stop" button hits the real `POST /api/v1/drills/{id}/stop`
   endpoint. "Reset" and "Inject" surface a clear "ships with F7 /
   F8 plans" message so the audience knows what's coming.

### Demo the user list (admin only)

1. Admin tab → "Users" card.
2. Shows every div:ide user with sub, role, last_login_at.
3. The "Disable" / "Enable" toggle is a stub (deferred to L3 admin
   user-management). On click, surfaces a clear message.

## Scripts

### `make demo`

Runs `tools/demo.sh`. Verifies API is up, lists scenarios, prints
the portal URL + sign-in hints, and exits. **Does not start any
drills.**

### `make demo-open`

Same as `make demo` but tries to open the portal in the default
browser via `xdg-open` / `open`.

### `tools/demo.sh --api http://other-host:8000`

Points at a remote stack instead of localhost.

### `tools/demo.sh --admin-sub alice --admin-pw hunter2`

Echoes the bootstrap admin sub + password in the output. Convenient
for screenshots or recording demos.

### `tools/login.py --user alice --password hunter2`

Mints an X-Divide-Token via the credential-login endpoint. For
SSH operators who prefer not to use the sign-in screen.

### `tools/issue_token.py --user alice --role admin`

Mints an X-Divide-Token locally with the HMAC secret. Works
without the API running. Use this for emergency tokens or pre-API
provisioning.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/portal/app/` returns 404 | Portal bundle not built | `cd services/portal/app && npm run build` |
| Sign-in returns 401 immediately | No admin user exists | Set `DIVIDE_BOOTSTRAP_ADMIN_*` env vars, `make restart` |
| Drill fails with "no Proxmox configured" | PVE env vars unset | Set `PROXMOX_*` env vars per `docs/PROXMOX-SETUP.md` |
| Topology graph empty | Scenario has 0-1 assets | Pick `red-vs-blue-baseline` instead |
| Demo runner says "API not reachable" | Stack not up | `make up` first |

## What this demo does NOT cover

- ~~**Multi-VM scenarios that actually run** — F3 (multi-VM
  scenarios + networks[]) is the next plan. The topology graph
  renders correctly today with the demo scenario, but
  `POST /drills` against it will fail at provisioning.~~ ✅ **F3
  done** — runner iterates `spec.networks[]`, creates bridges
  per network, attaches NICs per asset. Real PVE requires the
  operator to add the bridges per [`docs/F3-RUNBOOK.md`](F3-RUNBOOK.md)
  (PVE has no public API for `vmbrN` creation).
- **Scoring + leaderboard** — F5 (flag submission + scoring).
- **Multi-team exercises** — F6 (Exercise model).
- **Range templates + reset** — F7.
- **Blue-team SOC view** — F8 (SSE event stream).

These are documented in `docs/PLAN.md` §15 (the cyber-range
roadmap) and are the natural follow-up plans.

## See also

- [`docs/PLAN.md`](PLAN.md) §15 — the cyber-range roadmap
- [`docs/PORTAL-UI.md`](PORTAL-UI.md) — the F4-UI component inventory
- [`docs/USERS.md`](USERS.md) — credential-login operator guide
- [`docs/SETUP-UI.md`](SETUP-UI.md) — the setup wizard for paste-your-token
- [`docs/TEST-PRODUCT.md`](TEST-PRODUCT.md) — L1/L2/L3 ledger
