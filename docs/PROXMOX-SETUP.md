# Proxmox setup for div:ide

This guide walks through creating a **read-only** Proxmox user and API token for
div:ide. It assumes Proxmox VE 8.x and a single-node or cluster setup.

> **Why read-only?** Stage 2 (this stage) only ever queries Proxmox — it lists
> nodes, storage pools, and templates. Nothing is created, modified, or
> deleted. We promote the token to a write-capable role in Stage 3, only
> after this read-only path is verified end-to-end.

---

## 1. Create the user

In the Proxmox web UI:

1. **Datacenter → Permissions → Users → Add**
2. Fill in:
   - **User name:** `divide`
   - **Realm:** `pam` (Linux PAM authentication)
   - **Comment:** `div:ide cyber-drill orchestrator (read-only)`
   - **Enabled:** Yes
   - **Expire:** leave empty (or set a future date if you want a TTL)
3. Do **not** set a password — we'll use API token auth only.
4. Click **Add**.

## 2. Grant permissions

div:ide's day-1 wizard needs the PVE token to **create Linux bridges**
on the PVE node. The path it uses depends on the PVE version:

* **PVE 9 (default for new installs)**: the wizard creates bridges
  directly via `POST /nodes/{n}/network`. This requires `Sys.Modify`
  on `/nodes` -- **which is NOT in PVE's built-in `PVEAdmin` role**
  as of PVE 9. `Sys.Modify` was in PVE 8's `PVEAdmin` but PVE 9
  reserved it for `root@pam`. You need to create a custom role.
* **PVE 8.x with an SDN controller installed**: the wizard can use
  the SDN zone/vnet path (`SDN.Allocate` on `/sdn`). Most operators
  on PVE 9 will not have a controller, so prefer the direct path.

Grant three permissions (one role + two ACLs):

**Datacenter → Permissions → Roles → Create** (only needed once):

| Field | Value |
|---|---|
| Name | `DivideNetAdmin` |
| Privileges | check `Sys.Modify` only |

**Datacenter → Permissions → Add → User Permission** (three entries):

| # | User / Group | Path | Role | Propagate |
|---|---|---|---|---|
| 1 | `divide@pam` | `/` | `PVEAuditor` | Yes |
| 2 | `divide@pam` | `/sdn` | `SDN.Allocate` | No |
| 3 | `divide@pam` | `/nodes` | `DivideNetAdmin` | Yes |

Or, equivalently, via `pveum` on the PVE host:

```bash
# Custom role with Sys.Modify (PVE 9 requires this for direct bridge creation).
pveum role add DivideNetAdmin -privs Sys.Modify

# Read-only probe (PVEAuditor).
pveum aclmod divide@pam -role PVEAuditor -path / -propagate 1

# SDN.Allocate (only used if you opt into the SDN path).
pveum aclmod divide@pam -role SDN.Allocate -path /sdn

# Sys.Modify on /nodes (the new PVE 9 requirement for direct bridge creation).
pveum aclmod divide@pam -role DivideNetAdmin -path /nodes -propagate 1
```

**Why a custom role?** PVE 9's `PVEAdmin` role does not include
`Sys.Modify`. The built-in `Administrator` role DOES include it, but
granting `Administrator` is overkill (it includes cluster-wide
management). `DivideNetAdmin` is a minimal-role principle: just
`Sys.Modify`, nothing else.

`PVEAuditor` alone is **insufficient** -- it lets the API probe PVE
and list existing bridges, but the wizard's Recreate button needs
`Sys.Modify` to actually create them on PVE 9.

The wizard's Recreate button surfaces the literal PVE error +
copy-pasteable `pveum` lines when any role is missing. If you only
want to set up probes (no bridge creation), skip entries 2 and 3 --
but the wizard will be unable to complete setup.

If you want to skip the wizard entirely and use the env-var
fallback path (§6), only the first row is required -- the env-var
path never writes to PVE.

## 3. Create the API token

1. **Datacenter → Permissions → API Tokens → Add**
2. Fill in:
   - **User:** `divide@pam`
   - **Token ID:** `drill-token`
   - **Privilege Separation:** **unchecked** — single token, full `divide@pam` perms.
     (For stronger isolation, leave it checked and grant the token a
     separate, narrower role — we do that later in Stage 3+.)
3. Click **Add**. Proxmox shows the token secret **once** — copy it now.

The token secret is a UUID like `4ea3414f-d3a4-47b5-a2ed-19018f416cc0`. It is
**not recoverable** — if you lose it, delete the token and create a new one.

## 4. Day-1 setup: PVE bridge provisioning

The div:ide runner allocates one Linux bridge per
`spec.networks[]` declaration, starting at `vmbr100`. As of
**Q13 (direct bridge path)**, the wizard creates these directly
via PVE's node-level network API — no SDN controller, no
`/etc/network/interfaces` edits, no `ifreload`.

The wizard's Step 0:

1. **Probe PVE** (`GET /nodes/{n}/network`) to see what bridges
   already exist.
2. **Create one bridge per spec** (`POST /nodes/{n}/network`)
   with `type=bridge`, `address=<gateway>/<prefix>`, and
   `comments=div:ide:<scenario>/<network>`. PVE applies each
   bridge within ~1s and it shows up as a Linux bridge on the
   node.
3. **Verify** by re-polling `/nodes/{n}/network`; once every
   expected bridge is present, the wizard advances.

The wizard auto-skips Step 0 when all expected bridges already
exist on PVE, so it's safe to refresh the page.

### Why not PVE's SDN?

PVE 9's Simple-zone Vnets only materialize as Linux bridges on
the node when an external SDN controller (faucet, evpn, etc.) is
installed and configured. Most single-node lab installs don't
have one. Going through SDN also requires `SDN.Allocate`; the
direct path only needs `Sys.Modify` — which PVE 9 also reserves
for `root@pam`, but at least it's a smaller privilege that can be
wrapped in a minimal custom role (see §2 above).

For multi-node clusters that already run an SDN controller, the
SDN path is still supported: the `apply_bridges()` function in
`app/services/pve_bridges.py` accepts `method="sdn"` to fall back
to the legacy zone/vnet path. The wizard does not expose this
toggle today; if you need it, call the API directly with
`{"method": "sdn"}` or open an issue.

### Rollback

To remove a single bridge the wizard created, run on the PVE host:

```bash
pvesh delete /nodes/pve/network/vmbr100 -iface vmbr100
# or via the web UI: Datacenter -> Node -> pve -> Network -> vmbr100 -> Delete
```

The wizard does **not** write to `/etc/network/interfaces` and
does not create any SDN zone, so there is nothing else to roll back.

### PVE 9 Sys.Modify grant

If the wizard's Recreate button returns a 403 with the message
`Permission check failed (/nodes/pve, Sys.Modify)`, the token is
missing the `Sys.Modify` privilege on `/nodes`. Grant it (see §2
above) — the wizard will surface a copy-pasteable `pveum` snippet
and a web-UI walkthrough so the operator doesn't need to read
this doc to recover.

## 5. PVE connection: web setup (preferred)

**F-pve-config-ui + F-pve-bridge-wizard (SDN variant)**: as of these
releases, PVE host + token AND the Linux bridges can all be set up
from the browser. The API probes PVE with the supplied credentials
before persisting (so typos surface immediately), then creates the
Linux bridges via PVE's Software-Defined Networking API. No SSH
session to PVE, no editing `/etc/network/interfaces`, no
container restart.

Flow:

1. Open the portal: `http://localhost:8000/portal/app/`.
2. The wizard's **first** step asks for PVE host + user + token. Pre-fills
   the user + token ID with the values you created in §1-3.
3. Click **Save + connect**. The API calls `GET /api2/json/version`
   on PVE; if it returns, the credentials are written to the `pve_config`
   table. If it returns 401/403, the wizard shows the actual PVE error.
4. The wizard advances to **Step 0: PVE bridges**. It pre-flights PVE
   via `GET /api/v1/admin/pve-sdn-status` to confirm the token has
   `SDN.Allocate`. If it doesn't, the wizard renders the literal PVE
   error + a copy-pasteable `pveum aclmod` line (you granted this in §2).
5. Click **Set up PVE bridges**. The API calls
   `POST /cluster/sdn/zones` (one Simple zone named `divide`) and
   `POST /cluster/sdn/vnets` (one VNet per F3 bridge: `vmbr100`,
   `vmbr101`, ...). PVE auto-propagates each VNet as a Linux bridge
   on every node in the cluster. No reload command needed.
6. The wizard advances to admin bootstrap, scenario pick, team form,
   launch.

The endpoint is also exposed for the admin UI / curl:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"sub":"admin","password":"..."}' | jq -r .token)

# GET shows the active config (DB row if set, else env-var fallback)
curl -s http://localhost:8000/api/v1/admin/pve-config \
    -H "X-Divide-Token: $TOKEN" | jq

# POST a new config (probes PVE first; commits only on success)
curl -s -X POST http://localhost:8000/api/v1/admin/pve-config \
    -H "X-Divide-Token: $TOKEN" -H 'Content-Type: application/json' \
    -d '{
        "host":"https://192.168.0.10",
        "user":"divide@pve@pam",
        "token_id":"divide@pve@pam!drill-token",
        "token_secret":"<uuid-from-§3>",
        "verify_ssl":false,
        "node":"pve"
    }'

# DELETE to revert to the deploy/.env fallback (escape hatch)
curl -s -X DELETE http://localhost:8000/api/v1/admin/pve-config \
    -H "X-Divide-Token: $TOKEN"
```

`POST /admin/pve-config` **probes PVE before persisting** — a wrong
host, token, or user permission surfaces as a 502 with the actual PVE
error message. No DB write happens on failure, so a typo costs
nothing.

The token secret is stored plain-text in the `pve_config` row
(same risk profile as `users.password_hash`). It is **never returned**
from the API; the GET endpoint masks it as `"***"`.

Resolution order: `pve_config` row in DB (set via wizard or curl) >
`PROXMOX_*` env vars (see §6 below). Once a DB row exists, the
env-var fallback is dead until `DELETE /admin/pve-config` is called.

## 6. PVE connection: env-var fallback (alternative)

If you can't or don't want to use the web setup (e.g. provisioning is
done by automation that already has the env-var contract), edit
`deploy/.env` and the API will pick up the values on startup:

```env
PROXMOX_HOST=https://192.168.0.10    # your PVE host (no trailing slash)
PROXMOX_PORT=8006
PROXMOX_USER=divide@pve@pam           # full PVE user: divide + realm pve + realm pam
                                     # (yes, the doubled-@ is correct for token auth)
PROXMOX_TOKEN_ID=divide@pve@pam!drill-token
PROXMOX_TOKEN_SECRET=<paste-uuid>
PROXMOX_VERIFY_SSL=false             # true if PVE has a real cert
```

**Important**: `PROXMOX_TOKEN_ID` must be `<full-user>!<token-name>`, where
`<full-user>` is the user exactly as PVE shows it under **Datacenter → Users**
(e.g. `divide@pve@pam`). Proxmox GUI shows the full string when you list
tokens.

`PROXMOX_USER` must be the **same** full user string (no `!token-name` part).

### Why is `PROXMOX_USER` `divide@pve@pam` (with two `@`)?

That looks like a typo but it isn't. PVE token users are
`<unix-name>@<auth-source>@<realm>` — for a PAM-created user, both auth-source
and realm default to `pam`. So `divide@pve@pam` is the canonical name.

If you only set `PROXMOX_USER=divide@pve`, proxmoxer builds the auth header
as `PVEAPIToken=divide@pve!drill-token=<secret>`, which PVE rejects with
**401 Unauthorized**. The correct header is
`PVEAPIToken=divide@pve@pam!drill-token=<secret>`.

Quick verification:

```bash
TOKEN_ID='divide@pve@pam!drill-token'
SECRET='<your-uuid>'
curl -sk -w "\nHTTP %{http_code}\n" \
    -H "Authorization: PVEAPIToken=${TOKEN_ID}=${SECRET}" \
    https://192.168.0.10:8006/api2/json/version
# {"data":{"version":"9.1.7",...}} → HTTP 200
```

## 7. Validate

Restart the stack and call the API:

```bash
make restart
curl -s http://localhost:8000/api/v1/proxmox/health | python -m json.tool
```

Expected output (replace `<ver>` with your actual PVE version):

```json
{
  "status": "ok",
  "version": "<ver>",
  "release": "...",
  "repoid": "...",
  "host": "https://192.168.0.10"
}
```

If you see `502 Authentication failed`, the most common causes are:

1. **Wrong realm** — `PROXMOX_USER=divide@pam` should be `divide@pve`.
2. **Token revoked** — the GUI lets you delete tokens; secret is gone for good.
3. **Wrong secret** — copy/paste dropped a character; compare carefully.
4. **Token ID format** — must be `user@realm!tokenname`, no spaces.

You can also test the token directly with curl (no GUI needed):

```bash
curl -sk \
  -H "Authorization: PVEAPIToken=divide@pve!drill-token=<your-uuid>" \
  https://192.168.0.10:8006/api2/json/version
```

If curl returns `401` but the header looks right, regenerate the token.

## 8. Promote later (Stage 3+)

When we add write endpoints (clone/start/stop/delete VMs):

1. Go to **Datacenter → Permissions → Add → User Permission** for `divide@pam`.
2. Add a **second** permission line with role **`PVEVMAdmin`** and path `/v2/vm`.
3. Keep the original `PVEAuditor` permission as well — the broader one wins
   when paths overlap.

This way the token can write VMs but cannot manage storage pools, users, or
cluster config.

## 9. Runner adapter selection (Stage 5)

`RealProxmoxAdapter` is shipped in `services/api/app/runners/real_adapter.py`
and the runner factory (`build_runner()` in `services/api/app/runners/runner.py`)
automatically picks it when all of the following are true:

- `PROXMOX_HOST` is non-empty
- `PROXMOX_TOKEN_ID` is non-empty
- `PROXMOX_TOKEN_SECRET` is non-empty

If any are missing, the factory returns `MockProxmoxAdapter` so dev / CI
keep working without PVE creds.

There is **no code change needed to flip mock → real**: once your token
authenticates, restart the stack and the next `POST /api/v1/drills` will
clone real VMs.

If config looks set but the factory still returns the mock (and you see
"PROXMOX_* env present but invalid" in logs), inspect the values:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm api \
    python -c "from app.core.config import settings; print(repr(settings.proxmox))"
```

## 10. Promote for write operations (Stage 6+)

Read-only endpoints (Stage 2) work with `PVEAuditor`. Write operations
(clone, start, stop, destroy) need a stronger role. Run on the PVE host:

```bash
# Add PVEVMAdmin for the divide user at the /v2/vm path.
pveum acl modify /v2/vm --users divide@pve@pam --roles PVEVMAdmin

# Or, for a broader token (also lets the control plane manage storage
# pools + cluster config), grant PVEAdmin at /:
pveum acl modify / --users divide@pve@pam --roles PVEAdmin
```

> **PVE version note:** the flags are `--users` and `--roles` (plural)
> on PVE 8 and 9. PVE 7 and earlier used `--userid` and `--role`
> (singular). If your `pveum` rejects the plural form, run
> `pveum acl modify --help` to see what's accepted.

Verify:

```bash
pveum acl list
# Expect an entry: path=/v2/vm ugid=divide@pve@pam roleid=PVEVMAdmin
```

The `RealProxmoxAdapter` and `tools/upload_cloudinit_template.py` both
surface `403 Permission check failed` errors with a copy-pasteable
`pveum acl modify ...` hint when this is missing.

Once the role is granted:

```bash
# 1. Bootstrap a cloud-init template (Debian netinst ISO already on PVE).
make upload-template NAME=tpl-debian-cloudinit \
    ISO=local:iso/debian-13.4.0-amd64-netinst.iso

# 2. Start the smoke drill against it.
make live-drill SCENARIO=first-live-drill TIMEOUT=300
```

Step 1 creates a VM (`vmid` allocated by PVE), attaches the ISO as
`ide3`, adds a cloud-init drive as `ide2`, sets `template=1`. Boot it
once via the PVE GUI to install Debian + `qemu-guest-agent`, then run
the script again with `--convert-only <vmid>` to flip an already-existing
VM to a template (or rebuild via `make upload-template` if it wasn't
created with `--convert-only` from the start).
