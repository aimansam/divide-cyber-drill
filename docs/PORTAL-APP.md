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
4. `TokenBar` decodes the unverified payload (base64url) to show
   `signed in as alice · trainee` — **display only**; the server
   re-validates on every request.
5. Sign out clears `localStorage` and re-renders as anonymous.

See `app/core/auth.py` for the server-side validation.

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
