# Test UI (operator browser tool)

A single-page browser UI at `/portal/test/` that exposes the control-plane
endpoints as clickable cards. Useful for poking at scenarios, drills,
assets, audit log, and the PVE state without leaving the browser or
writing curl.

Not a portal. Not a dashboard. An operator tool.

## Open it

After `make up`, browse to:

```
http://localhost:8000/portal/test/
```

The page is served by the API container at `/portal/test/`. No login
(LAN-only tool, same as the wizard).

## What each card does

There are seven cards stacked top to bottom:

### 1. Scenario picker

Loads `GET /api/v1/scenarios` on page load into a dropdown. Click
**Load details** to fetch `/api/v1/scenarios/{name}` and display the
full scenario spec.

The loaded `scenario_id` is remembered by the **Run lifecycle** card.

### 2. Run lifecycle

- **Start drill** button → `POST /api/v1/drills {scenario_id}`. The
  new run's `run_id` is filled into the input.
- **Refresh** button → `GET /api/v1/drills/{id}` and shows the full
  row plus asset state. Pulls the assets list into card 4.
- **Auto-refresh** toggles a 2-second poll. It auto-stops when the
  run reaches a terminal state.

### 3. Cancel

Calls `POST /api/v1/drills/{id}/cancel` with optional `reason` +
`actor`. Disabled unless the run is in `pending`, `started`,
`spawning`, or `running` — the API itself enforces this with 409, the
UI just hides the button.

### 4. Assets

The asset rows from the current run, rendered as a small table:
`role | kind | status | pve_vmid | node | ip`. Refreshing the run
also refreshes this card.

### 5. Audit log

Calls `GET /api/v1/drills/{id}/audit` and shows the append-only
audit log for the run, oldest first. Each line is
`<at>  <action>  actor=<actor>  [details=...]`.

Useful for confirming lifecycle hooks fired (`run.started`,
`asset.spawned`, `run.completed` / `run.cancelled`).

### 6. Metrics

Calls `GET /metrics` (the Prometheus exposition endpoint) and shows
all `divide_*` samples. Has a substring filter above for narrowing
to one family (e.g. `divide_runs_total`).

### 7. Proxmox

Three stacked sections:
- **health**: `GET /api/v1/proxmox/health` → PVE version + reach
- **nodes**: `GET /api/v1/proxmox/nodes` → node + status table
- **templates**: `GET /api/v1/proxmox/templates` → VM templates

## API endpoints the UI calls

These are all real, first-class endpoints. None of them are wizard-only.

| UI card | Method + path |
|---|---|
| Scenario picker (load) | `GET /api/v1/scenarios` |
| Scenario picker (detail) | `GET /api/v1/scenarios/{name}` |
| Run lifecycle (start) | `POST /api/v1/drills` |
| Run lifecycle (refresh) | `GET /api/v1/drills/{id}` |
| Cancel | `POST /api/v1/drills/{id}/cancel` |
| Assets (via Run refresh) | `GET /api/v1/drills/{id}` (assets in body) |
| Audit log | `GET /api/v1/drills/{id}/audit` |
| Metrics | `GET /metrics` |
| Proxmox health | `GET /api/v1/proxmox/health` |
| Proxmox nodes | `GET /api/v1/proxmox/nodes` |
| Proxmox templates | `GET /api/v1/proxmox/templates` |

`GET /api/v1/drills/{id}` and `GET /api/v1/drills/{id}/audit` were
added specifically to support this UI (the previous list endpoint
returned summary rows only and didn't expose assets or audit).

## When to use this vs the wizard vs curl

| Tool | Best for |
|---|---|
| `/portal/test/` | poking at state: "did my drill start? what status?", "what templates does PVE have?", "show me the audit log for run N" |
| `/portal/` (wizard) | setting up a fresh deployment; not useful once setup is done |
| curl / httpx | scripting, CI, anything that needs reproducibility |

## When NOT to use this

- **For real drills.** Use `make live-drill` or the future portal
  (L2). This UI doesn't render progress bars or drill-specific state.
- **In production.** It's a dev tool. No auth, no rate limiting, no
  audit of UI clicks. Don't expose port 8000 to the public internet.

## Architecture notes

- **No framework**: vanilla HTML + ~250 lines of JS using `fetch()`.
  Same dark-theme palette as the wizard.
- **Single page**: no routing, no router state. Each card is
  independent — one card failing doesn't break the others.
- **No persistence**: refresh the page, lose the state. Re-enter the
  run id if you want to keep going.
- **Auto-refresh** runs at 2s polling. If the API is overloaded, the
  next click on Refresh cancels the timer.

## Files

| File | Purpose |
|---|---|
| `services/portal/test/index.html` | the page itself |
| `services/api/app/routers/drills.py` | added `GET /drills/{id}` + `/drills/{id}/audit` |
| `services/api/tests/test_test_ui.py` | smoke tests for both the endpoints and the page |
| `services/api/tests/conftest.py` | sets `DIVIDE_PORTAL_DIR` so tests see the portal |

## Limitations / future work

- **No real-time updates**. Polling at 2s is fine for short drills but
  not for hours-long scenarios. WebSocket / SSE is a future upgrade.
- **No drill duration display**. The run detail shows `duration_sec`
  but no auto-refresh shows the live delta. Add a watch if needed.
- **No input validation**. Drill id is just an `<input type="number">`;
  typo a digit and you get 404. Operationally fine, operator UX
  would benefit from autocomplete.
- **No copy-to-clipboard**. JSON values are clickable in the output,
  but a button to copy the request as curl would be a nice touch.
- **No dark/light toggle**. Dark only. Operators seem to like it.
