# User Portal (`/portal/app/`)

The user-facing browser portal — sign in, pick a scenario, watch a
drill live, download a debrief. Companion to:

- [`SETUP-UI.md`](SETUP-UI.md) — the one-time deploy wizard at `/portal/`
- [`TEST-UI.md`](TEST-UI.md) — the operator diagnostic tool at `/portal/test/`
- [`USER-REQUIREMENTS.md`](USER-REQUIREMENTS.md) — persona-side view of what
  each role can do today

## Open it

After `make up` (and after the React bundle is built — see below):

```
http://localhost:8000/portal/app/
```

The page is served by the API container at `/portal/app/`. FastAPI's
`StaticFiles` mount points at `services/portal/app/build/` (the Vite
output); the bundle is the React app, the API is at `/api/v1/*` as
for the other portals.

## Stack

| Layer | Pick |
|---|---|
| Bundler / dev server | **Vite 6** (`npm run dev`, `npm run build`) |
| Component model | **React 18 + TypeScript 5** (`strict: true`) |
| Styling | **Tailwind CSS 3** with shadcn/ui semantic tokens |
| Primitives | **shadcn/ui** — components live in `src/components/ui/`, copied into the repo so you own them |
| Icons | **lucide-react** |
| Auth | `X-Divide-Token` header on every `fetch()` (matches the FastAPI `current_token` dependency) |

The framework decision is recorded in [`docs/TEST-PRODUCT.md`](TEST-PRODUCT.md)
§Next plan (item #2 was about ditching vanilla for a real component
framework; this is the result).

## Repository layout

```
services/portal/app/
├── package.json           # one Vite project, one node_modules
├── vite.config.ts         # base: /portal/app/, dev server proxy to API
├── tailwind.config.js     # shadcn semantic tokens, dark mode
├── tsconfig*.json         # strict mode
├── index.html             # Vite entry — references /src/main.tsx
├── src/
│   ├── main.tsx           # createRoot + StrictMode
│   ├── app.tsx            # top-level layout, picks + tokens
│   ├── index.css          # @tailwind base + dark palette
│   ├── lib/
│   │   ├── api.ts         # fetch() wrapper, X-Divide-Token injection
│   │   └── utils.ts       # cn() — Tailwind class merge helper
│   └── components/
│       ├── ui/            # shadcn primitives (button, card, input)
│       └── portal/        # portal cards (token-bar, scenarios-card)
├── build/                 # Vite output (gitignored; serves /portal/app/)
└── .gitignore             # node_modules/, build/, *.tsbuildinfo
```

## Build & dev

```bash
# One-time:
make portal-install        # npm ci in services/portal/app/

# Production build (writes services/portal/app/build/):
make portal-build          # tsc -b && vite build (~2 s)

# Dev loop (HMR — browser updates in <100 ms):
make portal-watch          # vite dev server on :5173, proxies /api -> :8000
```

The bind mount in `deploy/docker-compose.yml` exposes
`services/portal/app/build` to the API container, so `make portal-build`
on the host is reflected on the next browser refresh — no API rebuild.

## How auth works in the UI

1. User pastes a token into the top-bar `TokenBar` component
   (`src/components/portal/token-bar.tsx`).
2. The token is stored in `localStorage["divide_token"]`.
3. Every `api.get()` / `api.post()` in `src/lib/api.ts` reads it and
   sets `X-Divide-Token: <token>` on the request.
4. `TokenBar` calls `useMe()` (`src/lib/auth.ts`) which hits
   `GET /api/v1/me` — the server returns the **verified** identity
   (`sub`, `role`, `iat`, `exp`, `ttl_remaining_s`) and the badge
   shows `signed in as alice · <role label> [verified]`. The old
   client-side JWT decode is gone — too easy to MITM.
5. Sign out clears `localStorage` and re-renders as anonymous.

See `app/core/auth.py` for the server-side validation.

**RBAC is enforced server-side.** The portal just forwards the
token; it does not implement role checks itself. As of L2 2.9,
every router in `/api/v1/*` enforces the persona matrix in
[`docs/USER-REQUIREMENTS.md` §2](../USER-REQUIREMENTS.md) via the
`require_role(...)` dependency. `red` and `blue` tokens are
filtered to their own runs (`started_by == sub`); admin/lead/observer
see all runs; the `/admin/*` endpoints are admin-only. Tokens are
minted via `tools/issue_token.py --user alice --role red --ttl 24h`;
`--role` choices are restricted to the five enum values.

## Role-aware composition

The portal renders a different set of cards for each role. The
single source of truth is `COMPOSITIONS` in `src/app.tsx`. The
server-side matrix from commit `4d840f9` is the second line of
defense — a misbehaving client can't bypass the gate, but
rendering the wrong cards for a role would produce "click and get
403" UX, so we hide them instead.

| Role       | Cards shown |
|------------|-------------|
| anonymous  | ScenariosCard, SignInBanner |
| admin      | ScenariosCard, PveOpsCard, ScenarioAuthoringCard, MyRunsCard ("All runs"), RunLifecycleCard, RunInspectorCard, AssetsCard, AuditExplorerCard |
| lead       | ScenariosCard, ScenarioAuthoringCard, MyRunsCard ("All runs"), RunLifecycleCard, RunInspectorCard, AssetsCard, AuditExplorerCard |
| red        | ScenariosCard, MyRunsCard ("My runs"), RunLifecycleCard, RunInspectorCard, AssetsCard, AuditExplorerCard |
| blue       | ScenariosCard, MyRunsCard ("My runs"), RunInspectorCard, AssetsCard, AuditExplorerCard (read-only) |
| observer   | ScenariosCard, MyRunsCard ("All runs"), RunInspectorCard, AuditExplorerCard (read-only) |

Read-only roles (blue, observer) don't get the cards that have
write buttons: `RunLifecycleCard` (Start + Cancel), `ScenarioAuthoringCard`
(Import + Archive + Restore), `PveOpsCard` (future upload flow).
`AssetsCard` is shown to blue but not observer — observer sees the
asset summary inline in `RunInspectorCard`, since asset detail
(vmids, IPs, SSH targets) is operator-facing.

The matrix is pinned by `tests/test_portal_app_role_composition.py`
(20 tests). Adding a new role is a two-place change: append to
`Role` in `services/api/app/core/auth.py` AND to `COMPOSITIONS`
in `app.tsx`. The static-check test fails loudly if either side
drifts. Each card file documents its role set in its module
docstring (e.g. `pve-ops-card.tsx` says "admin only"); a separate
test asserts the documentation is present so future cards can't
silently drop their role attribution.

## Card catalog

| Card | LOC | Purpose | Endpoints |
|------|-----|---------|-----------|
| `ScenariosCard` | ~110 | List + pick a scenario | `GET /api/v1/scenarios` |
| `TokenBar` | ~135 | Sign-in form, X-Divide-Token injection | `GET /api/v1/me` (identity) |
| `MyRunsCard` | ~120 | "My runs" / "All runs" list | `GET /api/v1/drills` |
| `RunLifecycleCard` | ~340 | Start / refresh / cancel own-only | `POST /api/v1/drills`, `GET /api/v1/drills/{id}`, `POST /api/v1/drills/{id}/cancel` |
| `RunInspectorCard` | ~140 | Full run detail (status, started_by, duration, assets) | `GET /api/v1/drills/{id}` |
| `AssetsCard` | ~190 | Copy-to-clipboard SSH target per asset | `GET /api/v1/drills/{id}` (assets[] section) |
| `AuditExplorerCard` | ~150 | Append-only audit timeline | `GET /api/v1/drills/{id}/audit` |
| `PveOpsCard` | ~250 | Read-only PVE health + storage + template status (admin) | `GET /api/v1/admin/probe`, `GET /api/v1/admin/storage`, `GET /api/v1/admin/drill-template-status` |
| `ScenarioAuthoringCard` | ~310 | Import / Archive / Restore YAML (admin + lead) | `POST /api/v1/scenarios`, `DELETE /api/v1/scenarios/{name}`, `POST /api/v1/scenarios/{name}/restore` |

## When to use this vs the wizard vs the test UI

| Tool | Audience | Purpose |
|---|---|---|
| `/portal/` | Operator (first run) | one-time deploy wizard |
| `/portal/test/` | Operator (day-to-day) | poke at state, see what scenario is loaded, audit |
| `/portal/app/` | Trainee + lead | the actual product — pick a scenario, run it, debrief |

## Day-1 scope (next-plan M1 + M3.1)

Shipped in the first commit:

- **TokenBar** with `X-Divide-Token` injection
- **ScenariosCard** — lists `/api/v1/scenarios` and lets the trainee
  pick one. Proves the auth pipeline round-trips.

Planned next (next-plan items M2, M3.2–M3.7, M4):

- **Run lifecycle card** with live progress bar (CSS-only, polls
  `/api/v1/drills/{id}` every 1 s)
- **Assets card** (table with status pills + a placeholder "Open
  console" button — wired to noVNC in M6)
- **Audit card** with substring filter
- **Download report** button → `GET /api/v1/drills/{id}/report` (M3.5)
- **Cancel modal** with reason + actor fields
- **Toast on error** for any 4xx/5xx

Each new card is ~10 minutes of work because shadcn provides
`<Card>`, `<Button>`, `<Input>`, etc. out of the box.

## Files

| File | Purpose |
|---|---|
| `services/portal/app/` | Vite project root |
| `services/portal/app/src/components/portal/` | Portal cards |
| `services/portal/app/src/components/ui/` | shadcn primitives |
| `services/portal/app/src/lib/api.ts` | fetch wrapper with X-Divide-Token |
| `services/api/app/main.py` | adds the `/portal/app` StaticFiles mount |
| `tests/test_portal_app_smoke.py` | 9 regression tests (build, bundle, mount) |
