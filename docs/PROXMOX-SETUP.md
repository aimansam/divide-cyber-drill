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

## 2. Grant read-only permissions

1. **Datacenter → Permissions → Add → User Permission**
2. Fill in:
   - **User / Group:** `divide@pam`
   - **Path:** `/`
   - **Role:** `PVEAuditor`  ← built-in read-only role
   - **Propagate:** Yes
3. Click **Add**.

`PVEAuditor` grants access to read-only APIs (version, nodes, storage, VM
config). It does **not** allow creating, modifying, or deleting VMs — exactly
what we want at this stage.

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

## 4. Fill in `deploy/.env`

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

## 5. Validate

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

## 6. Promote later (Stage 3+)

When we add write endpoints (clone/start/stop/delete VMs):

1. Go to **Datacenter → Permissions → Add → User Permission** for `divide@pam`.
2. Add a **second** permission line with role **`PVEVMAdmin`** and path `/v2/vm`.
3. Keep the original `PVEAuditor` permission as well — the broader one wins
   when paths overlap.

This way the token can write VMs but cannot manage storage pools, users, or
cluster config.

## 7. Runner adapter selection (Stage 5)

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

## 8. Promote for write operations (Stage 6+)

Read-only endpoints (Stage 2) work with `PVEAuditor`. Write operations
(clone, start, stop, destroy) need a stronger role. Run on the PVE host:

```bash
# Add PVEVMAdmin for the divide user at the /v2/vm path.
pveum acl modify /v2/vm --userid divide@pve@pam --role PVEVMAdmin

# Or, for a broader token (also lets the control plane manage storage
# pools + cluster config), grant PVEAdmin at /:
pveum acl modify / --userid divide@pve@pam --role PVEAdmin
```

Verify:

```bash
pveum acl list /
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
