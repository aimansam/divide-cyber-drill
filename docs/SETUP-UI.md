# Setup wizard (web UI)

> **Note (F3-prep, 2026-08-24):** the user portal now has a
> **SignInCard** that lets operators log in with username +
> password instead of pasting a token. See
> [`docs/USERS.md`](USERS.md) for the operator guide. This
> wizard still mints tokens via `tools/issue_token.py` for
> one-shot admin work; the sign-in screen handles day-to-day
> login.

The **div:ide setup wizard** is a 4-step browser UI that takes an operator
from a fresh PVE host to a working drill template + first-live-drill,
without SSH-ing into Proxmox to drive the installer.

Open it at `http://<your-dev-box>:8000/portal/` after running
`make up`. No login required (LAN-only; L2 will add a token gate).

## What it does

1. **Proxmox connection** — confirms the API token in `.env` can reach
   PVE, and shows which privileges are present vs. missing.
2. **Token permissions** — tells you the exact `pveum` command to run on
   PVE so the wizard can create templates (one-time, ~30 sec).
3. **Drill template** — uploads a Debian cloud image and creates
   `tpl-debian-cloudinit` on PVE in one shot. Manual-install fallback
   path also supported.
4. **Run the first drill** — kicks off `first-live-drill` so you can see
   the whole flow without typing `make` commands.

Total wall time once PVE permissions are set: ~10 minutes.

## Prerequisites

You need:

| What | Where | Why |
|---|---|---|
| Docker compose stack running | dev box | the API serves the wizard |
| API token (PVEVMAdmin) in `.env` | dev box | the wizard inherits the token's privileges |
| `pve` reachable from the API container | dev box | the wizard calls PVE directly |
| A Debian cloud image (.qcow2) | your computer | uploaded in step 3 |

The token is the one created during `docs/PROXMOX-SETUP.md §5`
(`divide@pve@pam!drill-token`). It needs:

- **For running drills** (always required): `PVEVMAdmin` on `/` with `propagate=1`
- **For the wizard to create templates** (added during step 2): `PVEDatastoreAdmin` (built-in PVE role covering `Datastore.Allocate`, `Datastore.AllocateSpace`, `Datastore.Audit`)
  on `/storage` with `propagate=1`

If you'd rather not give the token storage privileges, use the **manual
install** path in step 3 — no extra ACL needed.

## The 4 steps in detail

### Step 1 — Proxmox connection

The wizard pings PVE and lists:

- Whether the token can reach PVE (and what version)
- Which drill privileges are present (`VM.Allocate`, `VM.Clone`,
  `VM.PowerMgmt`)
- Which setup privileges are present (`Datastore.AllocateSpace`,
  `Datastore.Allocate`, `Datastore.Audit`)
- Storage pools + free space (so the operator knows where the qcow2 will land)
- Nodes (so the dropdown has valid choices)

If you see a green checkmark on the drill privileges, you're done with
PVE setup. If setup privileges are missing, the wizard tells you the
exact `pveum` command to run.

### Step 2 — Token permissions

The wizard can't grant its own privileges (no API token can), so this
step is one human action:

```bash
ssh root@192.168.0.10
pveum acl modify /storage --users divide@pve@pam --roles PVEDatastoreAdmin --propagate=1
exit
```

Note: PVE 9 expects `--roles` (plural). `--role` (singular) is the PVE 7 form
and PVE 9 rejects it.

After running it, click **"I've run it — re-probe"** to refresh.

If you can't or won't grant `PVEDatastoreAdmin`, use **Option B** in step 3
(manual install). The wizard never forces this grant.

### Step 3 — Drill template

Two options:

#### Option A — Upload cloud image (recommended)

1. Download `debian-13-genericcloud-amd64.qcow2` (~270 MB) from
   <https://cloud.debian.org/images/cloud/trixie/latest/> to your laptop
2. Drop the file in the wizard's file picker
3. Click **Upload & import** — the wizard streams the file to PVE
   storage with a progress bar
4. Confirm the template name (default: `tpl-debian-cloudinit`)
5. Click **Create template** — the wizard calls PVE to:
   - Allocate a new VMID
   - Create a VM with cloud-init drive wired in
   - Import the qcow2 as scsi0
   - Set name + tags
   - Flip `template=1`

This takes ~30 seconds after the upload.

#### Option B — Manual install via existing ISO

If you already have a Debian ISO on PVE's `local` storage (the
screenshot showed `debian-13.4.0-amd64-netinst.iso` is present on
yours), you can install manually:

1. Open PVE GUI → **Create VM**
   - VMID: any (e.g. 9000)
   - Name: `tpl-debian-cloudinit`
   - OS: Do not use any media
   - System: default
   - Disks: scsi0, 20 GB, local-lvm
   - CPU: 2 cores
   - RAM: 2048 MB
   - Network: virtio, vmbr0
2. **Options** → uncheck **Template** (so you can boot it)
3. **Hardware** → **CD/DVD Drive** → Use ISO → `local:iso/debian-13.4.0-amd64-netinst.iso`
4. **Start** → **Console** → walk through Debian installer
5. After reboot, in the VM:
   ```bash
   apt-get update
   apt-get install -y qemu-guest-agent
   systemctl enable qemu-guest-agent
   shutdown -h now
   ```
6. Wait for VM to actually power off
7. Back in the wizard: enter VMID 9000 + node `pve` → **Mark as template**

### Step 4 — Run the first drill

With the template in place, this is one button click. The wizard POSTs
to the existing `/api/v1/drills` endpoint with scenario_id resolved by
name, so you don't need to look up IDs.

After ~1–3 min, the run reaches `succeeded` state. The drill record has
`pve_vmid` populated, `audit_log` has `run.started` + `asset.spawned` +
`run.completed` entries, and the asset row transitions to `stopped`
after teardown.

This matches L1 criteria **1.3–1.9** from `docs/TEST-PRODUCT.md`.

## API endpoints

The wizard is a thin UI over these admin endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/admin/probe` | one-shot PVE snapshot |
| `GET`  | `/api/v1/admin/storage` | list storage pools |
| `POST` | `/api/v1/admin/upload-qcow2` | stream a cloud image to PVE |
| `POST` | `/api/v1/admin/create-template` | turn uploaded qcow2 into template |
| `POST` | `/api/v1/admin/set-template/{vmid}` | flip template=1 on existing VM |
| `GET`  | `/api/v1/admin/progress/{kind}/{job_id}` | poll job status |
| `GET`  | `/api/v1/admin/progress` | list in-flight jobs |
| `GET`  | `/api/v1/admin/drill-template-status` | is `tpl-debian-cloudinit` ready? |
| `POST` | `/api/v1/admin/start-first-drill` | kick off `first-live-drill` |

All endpoints return JSON. The wizard polls `/progress/{kind}/{job_id}`
once per second during long-running jobs (template creation).

## Architecture notes

- **No auth on `/api/v1/admin/*`**: this is a LAN-only tool. L2 will
  add token middleware + an admin role; until then, anyone on the LAN
  can hit these endpoints. Don't expose port 8000 to the public
  internet.
- **Upload dir**: large files land in `/tmp/divide-uploads/` (or
  wherever `DIVIDE_UPLOAD_TMP_DIR` points). The local copy is removed
  after the upload completes; PVE retains the file under
  `local:import/`.
- **Background tasks**: `/create-template` returns immediately with a
  `job_id`. The actual creation runs as a FastAPI `BackgroundTasks`
  callback, with progress published to Redis. If the API container
  restarts mid-creation, the job is lost — re-issue the request.
- **No CORS changes needed**: the portal is served by the same origin
  as the API (`http://localhost:8000`), so the browser's same-origin
  policy applies and the wizard's `fetch()` calls work without CORS
  headers.

## When to use the runbook instead

The wizard covers the common case. For edge cases use the runbook:

- **Multi-node clusters** (template needs to live on every node):
  `docs/LIVE-DRILL-RUNBOOK.md §4` walks through manual creation on
  each node.
- **Custom cloud-init user-data** (SSH keys, packages to preinstall):
  edit `services/portal/index.html` step 3 form to add the
  `cicustom` fields, or build templates via `terraform-templates/`.
- **Windows / Kali templates** (Phase 2 work): the wizard is wired for
  Linux VMs only. Add a `kind: vm` selector to step 3 to generalize.
- **Air-gapped PVE**: the wizard needs the API container to reach PVE
  directly. If your PVE has no route from the API host, the wizard
  will fail at step 1 and you must use the runbook + manual
  `qm` commands on the PVE host itself.

## Troubleshooting

**Wizard says "PVE unreachable" but `curl https://pve:8006/api2/json/version` works.**
The token has wrong scheme/host. Edit `.env`, restart the API.

**Step 3 upload gets `403 permission denied`.**
The token lacks `Datastore.AllocateSpace`. Re-run step 2 — the
`pveum` command. If you ran it as the wrong user (`divide@pve` vs
`divide@pve@pam`), fix and re-run.

**Step 3 "Create template" hangs at "importing disk".**
Check PVE task list (Datacenter → pve → Task History). Common cause:
not enough free space on `local-lvm`. Pre-flight in step 1 should
have warned about this.

**Step 4 "Start first-live-drill" returns 500.**
Check `docker compose logs api`. Most common: scenario not in DB —
run `make sync-scenarios`.

## Where to go next

The wizard is one-time use. Once the template is registered, the
platform is ready for actual drills — and the entry point changes:

- **Trainee / lead:** open [`/portal/app/`](../services/portal/app/index.html)
  — the user portal. React/Vite + Tailwind + shadcn/ui. Sign in with
  a token (mint one with `python3 tools/issue_token.py --user
  alice --role trainee --ttl 1h`), pick a scenario, run a drill.
  See [`PORTAL-APP.md`](PORTAL-APP.md).
- **Operator (day-to-day):** open [`/portal/test/`](../services/portal/test/index.html)
  — this UI. Poke at state, see what's running, inspect audit
  logs. See [`TEST-UI.md`](TEST-UI.md).
- **CLI for CI / scripts:** `make live-drill SCENARIO=first-live-drill TIMEOUT=300`.
