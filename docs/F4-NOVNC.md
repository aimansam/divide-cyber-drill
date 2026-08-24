# F4 Runbook — noVNC Console Per Asset

> **Status:** F4 shipped (`9c7a583` + `e28ed7a`). Every running
> asset now exposes a noVNC console via
> `GET /api/v1/drills/{id}/assets/{a}/console` + WebSocket proxy.
>
> **Audience:** operators running an active drill who want a
> pixel-perfect view of any running VM. F3 takes care of getting
> the topology live; F4 takes care of looking at the VMs.

## TL;DR

For a drill that's running, click **Open console** (terminal icon)
next to any running asset on the **Drill console** tab. A small
**VNC console** card slides in below the asset list, requests a
PVE VNC ticket via the API, opens a WebSocket through the API
proxy, and renders the first PNG frame the proxy gets back from
PVE.

For "just look at my VM" use cases (boot-time inspection, "did it
cloud-init?", "what's my kali prompt?"), the default view (PNG
snapshot + Connect button) is enough. For full mouse / keyboard
forwarding, click **Connect**.

## How the proxy works

```
+----------------+        +-----------------+        +--------------+
| Browser        |  WS    |  div:ide API    |  WS    |  PVE         |
| noVNC client   | <----> |  console_proxy  | <----> |  vncproxy    |
+----------------+        +-----------------+        +--------------+
        ^                            ^                        ^
        | token in                   | RBAC, ticket           | ticket in URL
        | ?token= (or                | issuance, refresh       | (server-side)
        |  WS subprotocol)           |
```

The browser never sees the PVE token. The API issues a PVE ticket
on each console-open, holds it for the lifetime of the socket,
and re-issues on every retry. This means:

  * **RBAC is server-enforced.** A red/blue who isn't entitled to
    the run gets `4403` from the WS proxy; no token is leaked.
  * **Tickets rotate.** A new ticket is issued on every console
    open; if the operator leaves a console open for the
    full 2-hour ticket lifetime, they hit `4409` and the UI
    re-connects with a fresh ticket.
  * **Audit-friendly.** The console-open is observable in logs
    via the existing WebSocket lifecycle (no audit row by
    design; consoles aren't a state change).

## Endpoint contract

### HTTP — `GET /api/v1/drills/{run_id}/assets/{asset_id}/console`

```http
GET /api/v1/drills/42/assets/7/console HTTP/1.1
Host: divide.local
X-Divide-Token: <admin-token>

200 OK
Content-Type: application/json

{
  "asset_id": 7,
  "run_id": 42,
  "vmid": 9100,
  "node": "pve",
  "ticket": "PVE:...",
  "port": 5900,
  "ws_path": "/api/v1/drills/42/assets/7/console/ws",
  "expires_in_seconds": 7200
}
```

Errors:

| HTTP | When |
|---|---|
| 401 / 403 | Caller isn't authenticated, or isn't entitled to view the run. |
| 404 | Run or asset doesn't exist (don't leak existence to non-admins). |
| 409 | Asset hasn't been cloned yet (`pve_vmid` is `null`). |
| 502 | PVE rejected the ticket (transient — retry). |

### WebSocket — `/api/v1/drills/{run_id}/assets/{asset_id}/console/ws`

Browsers can't attach custom headers to WS, so the proxy accepts
the token in `?token=` query string. The portal does both:

- `X-Divide-Token` header on the upgrade (works in some clients)
- `?token=` query string fallback (works everywhere)

The proxy uses the standard 4xxx close-code range for failures:

| Code | When |
|---|---|
| 4401 | Token missing or invalid. |
| 4403 | RBAC denied. |
| 4404 | Run or asset not found. |
| 4409 | Asset not yet cloned. |
| 4502 | PVE upstream unavailable (vncproxy API down). |
| 1000 | Normal disconnect. |

## Why a stripped-down client, not @novnc/novnc?

We ship ~80 lines of canvas-based render in `ConsoleCard` rather
than embedding @novnc/novnc (~700 KB minified). The portal bundle
budget is 280 KB; F4 keeps us under that. If a future plan needs
full mouse + keyboard forwarding + clipboard, we add the noVNC
bundle then. Today the "Connect" button does a basic bidirectional
byte pump (RFB negotiation happens over the wire; the canvas
renders whatever PNG frames come back).

## RBAC matrix

| Role | Consoles for own run | Consoles for any run |
|---|---|---|
| admin | yes | yes |
| lead | yes | yes |
| observer | yes | yes |
| red | yes | no (403) |
| blue | yes | no (403) |
| unauthenticated | no (401) | no (401) |

The visibility check is `can_view_run(token, run)`; observers and
red/blue only see their own runs; admin/lead see everything.

## What an operator does (5-step recipe)

1. Start a drill (F3-RUNBOOK + the cyber-range demo).
2. Open the **Drill console** tab (auto-navigated after POST
   `/api/v1/drills`).
3. Find the assets table; wait until assets are `running`.
4. Click the **terminal icon** next to a running asset.
5. A **VNC console** card opens below the assets list with a
   Connect button. Click Connect for interactive mode.

If the VM doesn't respond within 2 seconds, you'll see "WebSocket
failed". Check:

- Is the asset actually running? (`status === 'running'` in the row)
- Is the run's node the one your PVE console expects?
  (`node=pve` in the VNC ticket body)
- Is PVE listening on `:8006` from the API host? (`pvesh get /` works?)

## Testing locally

### Mock-only path

Without PVE, all console endpoints are wired through
`MockProxmoxAdapter`. The mock returns a deterministic ticket
`mock-ticket-{vmid:04x}` so tests can assert exact values:

```python
# services/api/tests/test_f4_novnc.py
async def test_mock_adapter_issues_deterministic_ticket(adapter):
    t = await adapter.get_vnc_ticket(9100, "pve")
    assert isinstance(t, VncTicket)
    assert t.ticket == "mock-ticket-238c"  # 9100 hex
    assert t.port == 5900 + 9100 % 1000  # 6900
```

To exercise the proxy without PVE, run the full suite with `make
test`. The portal's ConsoleCard renders the placeholder canvas and
the WS proxy accepts the mock ticket.

### Real PVE path

```bash
# On the PVE node
# 1. Confirm vncproxy is enabled (default in PVE)
pvesh get /nodes/pve/qemu/9100/vncproxy

# 2. From the API host
curl -X POST -H "Authorization: PVEAPIToken=..." \
  https://pve.local:8006/api2/json/nodes/pve/qemu/9100/vncproxy
# Expected: {"data": {"ticket": "PVE:...", "port": "5900"}}
```

If that returns 200, the same call via our `RealProxmoxAdapter`
will return a real ticket. The portal then:

1. POSTs the WS upgrade request against
   `/api/v1/drills/{id}/assets/{a}/console/ws`.
2. The proxy opens a WSS connection to
   `wss://pve.local:8006/api2/json/nodes/pve/qemu/9100/vncproxy?port=5900&vncticket=PVE:...`
3. Bytes are pumped both ways.

## What's NOT in this runbook

- **noVNC JS bundle** — for richer clients (mouse forwarding,
  clipboard, ResizeObserver-driven dynamic sizing). When needed,
  we'll add `@novnc/novnc` as a separate bundle chunk.
- **Multi-monitor VMs** — the API issues one ticket per asset;
  an asset with display heads >1 isn't fully modelled yet.
- **Console recording** — every minute of console video to
  minio is left for an F8 (SOC view) follow-up.

## See also

- [`docs/DEMO.md`](DEMO.md) — the operator's demo walkthrough
- [`docs/F3-RUNBOOK.md`](F3-RUNBOOK.md) — the F3 bridge setup
- [`docs/PLAN.md`](PLAN.md) §15 — F4 unblocks F8 (SOC view); the
  console is the building block for live event overlays.
