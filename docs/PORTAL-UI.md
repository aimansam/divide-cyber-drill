# div:ide Portal UI — Cyber-Range View Layer

> **Status:** F4-UI complete (commits `cd66060` + `146f91b` + `c2ccddf`).
> **Audience:** operators (anyone with a verified div:ide identity).

## What is F4-UI?

F4-UI is the visual layer that turns div:ide from a "list of admin
cards" into an actual cyber range. It reorganises the portal around
the **view tabs** every real cyber-range platform exposes:

| Tab | Purpose | Who sees it |
|---|---|---|
| **Dashboard** | KPIs at-a-glance + recent runs | All authed roles |
| **Operate** | Start a drill (pick → start → monitor) | All authed roles |
| **Observe** | Live drill console (status, assets, audit, topology) | All authed roles |
| **Admin** | PVE health, scenario library, user list, range operator console | admin + lead |
| **History** | Past runs, filterable by status | All authed roles |
| **Profile** | Per-user stats (your runs, your success rate) | All authed roles |

This is the same shape used by TryHackMe (Home / Learn / Rooms /
Profile), HackTheBox (Dashboard / Labs / Teams / Pro Labs / Ranking),
RangeForce (Home / Skills Labs / Solo Range), Immersive Labs
(Resilience Score / Crisis Simulation / Cyber Drills), SecDojo, and
CyLab (picoCTF). We're matching the universal pattern.

## New components shipped

### TopNav (`components/portal/top-nav.tsx`)
Brand bar + role-aware view tabs + role badge + sign-out user menu.
Hash routing (no `react-router` dep). Tabs filtered per role:
admin/lead see all 6; red/blue/observer see 5 (no Admin).

### DashboardCard (`components/portal/dashboard-card.tsx`)
KPI tiles (in-progress, today, success rate, my runs) + recent-runs
list with status pills. Empty state when no history.

### KpiTile (`components/portal/kpi-tile.tsx`)
One metric, big number, optional sublabel + icon + tone
(default/success/danger/warning/info). Used by DashboardCard.

### StatusPill (`components/portal/status-pill.tsx`)
Unified status colors across the portal. RUNNING=sky+pulse dot,
SUCCEEDED/=emerald, FAILED=red, TIMEOUT=amber, CANCELLED/STOPPED=slate,
ORPHANED=orange, UNKNOWN=slate-?. Replaces 8 places that hand-rolled
status colors.

### EmptyState (`components/portal/empty-state.tsx`)
Friendly placeholder for empty lists with icon + title + description
+ optional CTA.

### useHashRoute (`hooks/use-hash-route.ts`)
Minimal hash-based router. `window.location.hash = "#/operate"`
switches view. `history.replaceState` (not pushState) so the back
button stays usable. Strips query strings.

### TopologyGraph (`components/portal/topology-graph.tsx`)
Hand-rolled SVG (no external dep) that lays out a scenario's assets
left-to-right as red zone, router/firewall, blue zone. Role-based
classification:
- `attacker` / `red` / `offensive` / `pentester` → red zone
- `router` / `firewall` / `gw` → router zone
- `victim` / `blue` / `defender` / `target` / `log-aggregator` /
  `server` / `workstation` / `client` → blue zone
- everything else → unassigned

Connection lines drawn between zones with dashed strokes.
Empty state when no scenario is picked.

The visual signature: RangeForce's "Battle Range", HTB's "Network Map",
Immersive Labs live-exercise console, CyLab dashboard all show
similar graphs. We match the convention; F3 (multi-VM scenarios)
will make the segments real rather than synthesised.

### DrillConsole (`components/portal/drill-console.tsx`)
The dedicated live-drill view. Replaces the previous
"Observe tab = 3 cards stacked" pattern. Shows:

- Status header with **LIVE** pulse badge (only while RUNNING or PENDING)
- Run metadata: id, scenario name, started_by, live duration timer
- Topology preview (delegates to TopologyGraph)
- Asset table (compact AssetsCard)
- Audit feed (compact AuditExplorerCard)
- Prominent **Download report** button when the run is terminal

Polling cadence: every 2s while live, 5s while terminal.

### UserListCard (`components/portal/user-list-card.tsx`)
Admin view of every div:ide user. Renders sub, role, disabled/active
badge, last_login_at. The disable/enable toggle is wired to a stub
endpoint and falls back to a clear "deferred to L3 admin-user-management"
message on 404/501 — that's the next iteration's plan, not a silent
failure.

### OperatorConsoleCard (`components/portal/operator-console-card.tsx`)
The range operator's lens. Lists every RUNNING/PENDING run with
quick-action buttons:

- **Stop** (real, hits `POST /api/v1/drills/{id}/stop`)
- **Reset** (deferred to F7)
- **Inject** (deferred to F8)

Auto-polls every 5s.

### ProfileCard (`components/portal/profile-card.tsx`)
Per-user progress view. Wraps a focused DashboardCard scoped to the
current user. Server-side visibility filter IS the profile filter —
no double-filtering on the client.

### Toast + ToastHost (`components/portal/toast.tsx`)
Minimal toast queue, no external library. Three kinds
(info / success / error), auto-dismiss after 4s, sticky when
`timeoutMs=0`. ToastHost wraps the entire app tree so any
component can call `useToasts().success("Saved")`. Used by
DrillConsole, OperatorConsoleCard, UserListCard.

### MyRunsCard status filter
A status filter pill row above the list
(all / pending / running / succeeded / failed / timeout / cancelled).
Active pill is highlighted. Auto-polls every 5s so History stays
current.

## Bundle impact

| Stage | JS bundle | gzip | Notes |
|---|---|---|---|
| Pre-F4-UI (F3-prep) | 219 KB | 67 KB | SignInCard + login/logout |
| F4-UI commit 1 | 231 KB | 70 KB | +12 KB: TopNav, Dashboard, KpiTile, StatusPill, EmptyState, useHashRoute |
| F4-UI commit 2 | 236 KB | 71 KB | +4.6 KB: TopologyGraph, DrillConsole |
| F4-UI commit 3 | 246 KB | 74 KB | +10 KB: UserList, OperatorConsole, Profile, Toast, MyRuns filter |

Total F4-UI overhead: **+27 KB** (≈+10% gzip). Within the 280 KB
budget. Still well under the 250 KB lazy-load trigger for the
admin-only cards (PveOpsCard, ScenarioAuthoringCard, UserListCard,
OperatorConsoleCard).

## Tests

- `tests/test_f4_ui_components.py` — 66 tests for the new surface
  (file existence, exports, props, data-testid, app.tsx wiring,
  role-permission gating, bundle size)
- `tests/test_portal_app_role_composition.py` — rewritten for F4-UI;
  pins TopNav tab visibility per role + every card's view case in
  app.tsx (22 tests)
- `tests/test_sign_in_card.py` — 2 obsolete COMPOSITIONS tests
  replaced with F4-UI-aware equivalents

Total: **484 tests passing** (was 415 before F4-UI; +69 new).

## What F4-UI does NOT include

- **Real topology from F3** — the graph lays out whatever role
  strings the scenario YAML defines. F3 (multi-VM scenarios) will
  give it real segments, bridges, and asset-to-network attachments.
- **Admin user-management mutations** — UserListCard lists + shows
  the disable toggle as a stub. CRUD mutations ship with the L3
  admin UI plan.
- **Range templates + reset** — OperatorConsoleCard surfaces Reset
  as a stub. F7 ships the actual reset endpoint.
- **Event injection** — OperatorConsoleCard surfaces Inject as a
  stub. F8 ships the injection UI.
- **Theme toggle / light mode** — dark only. Trivial to add later.
- **Mobile breakpoints / drawer nav** — usable on tablet but not
  specifically tuned. Tablet checks would be a follow-up.

## See also

- [`docs/PLAN.md`](PLAN.md) §15 — the cyber-range roadmap that
  F4-UI is the visual entry-point for
- [`docs/USERS.md`](USERS.md) — operator guide for credential
  login (F3-prep; the front door before F4-UI)
- [`docs/USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md) §2 — the
  permission matrix that drives TopNav's tab visibility
