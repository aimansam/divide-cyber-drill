# Live Drill Runbook

Step-by-step instructions for executing the first real Proxmox VM clone
end-to-end. Use this whenever you need to (re)verify the platform
against a live PVE host.

> **TL;DR**
>
> 1. `pveum acl modify /v2/vm --userid divide@pve@pam --role PVEVMAdmin` (PVE host shell)
> 2. `make upload-template NAME=tpl-debian-cloudinit ISO=local:iso/<debian>.iso` (dev box)
> 3. Install Debian in the new VM via PVE GUI (incl. `qemu-guest-agent`)
> 4. `make upload-template NAME=tpl-debian-cloudinit` (converts VM to template)
> 5. `make preflight` — must report 8/8
> 6. `make live-drill SCENARIO=first-live-drill TIMEOUT=300`
> 7. Open http://localhost:3000 — watch Panel 1 light up

---

## 0. Prerequisites

| What | Where | How to verify |
|---|---|---|
| Docker compose stack up | dev box | `docker compose -f deploy/docker-compose.yml ps` |
| Proxmox PVE 8.x or 9.x reachable | dev box | `curl -k https://<pve>:8006/api2/json/version` returns JSON |
| Token user `divide@pve@pam!drill-token` exists on PVE | PVE host | `pveum user list` + `pveum user token list divide@pve@pam` |
| Token privileges: `PVEVMAdmin` on `/v2/vm` | PVE host | `pveum acl list --userid divide@pve@pam` |
| Debian netinst ISO uploaded to PVE | PVE GUI | Datacenter → pve → local → ISO Images → Upload |
| Outbound network from dev box to PVE on :8006 | network | `nc -zv <pve> 8006` |

---

## 1. Grant PVEVMAdmin (PVE host shell)

The `divide@pve@pam` user needs PVEVMAdmin on `/v2/vm` to clone,
start, stop, and destroy VMs. Without this, the runner will fail with a
403 from PVE.

```bash
# On the PVE host shell
pveum acl modify /v2/vm --userid divide@pve@pam --role PVEVMAdmin

# Confirm
pveum acl list --userid divide@pve@pam
```

**Expected output:**

```
~ pveum acl list --userid divide@pve@pam
"/v2/vm" --userid divide@pve@pam --role PVEVMAdmin
```

If you don't see that line, the grant didn't take. Re-run the command.

**Troubleshooting:**

- If `pveum` isn't found: you're on the wrong host. SSH to the PVE host.
- If the user doesn't exist: `pveum user add divide@pve@pam --comment "div:ide runner"`
- If the role doesn't exist: `pveum role list | grep PVEVMAdmin` — it should be there by default in PVE 8+.

---

## 2. Verify env on dev box

The API container needs the right env to pick `RealProxmoxAdapter` over the mock.

```bash
cat deploy/.env | grep -E '^(PROXMOX_HOST|PROXMOX_USER|PROXMOX_TOKEN_ID)='
```

**Expected:**

```
PROXMOX_HOST=https://192.168.0.10       # your PVE
PROXMOX_USER=divide@pve@pam             # canonical @pam
PROXMOX_TOKEN_ID=divide@pve@pam!drill-token
```

`PROXMOX_USER` must contain the `@pam` suffix — PAM users always have
this. If your env shows `divide@pve` instead, fix it.

`PROXMOX_TOKEN_ID` is the FULL `<user>!<token-name>` string — that's
the convention for proxmoxer's token auth.

---

## 3. Run preflight (dev box)

```bash
make preflight
```

**Expected: 8/8 checks PASS.**

```
======================================================================
PRE-FLIGHT REPORT
======================================================================
  [PASS] /healthz responds 200                              env=dev, version=0.1.0
  [PASS] PROXMOX_* configured (RealProxmoxAdapter)          version=9.1.7, ok=?
  [PASS] PVE nodes reachable                                1 node(s): pve
  [PASS] Template 'tpl-debian-cloudinit' exists on PVE      vmid=9000
  [PASS] Scenario 'first-live-drill' in DB                  id=3
  [PASS] /metrics live on API                               12 divide_* metric families, ...
  [PASS] Prometheus scraping divide-api                     http://api:8000/metrics -> up
  [PASS] Grafana dashboard 'divide-drill-platform' loaded   title='div:ide — Drill Platform', panels=6
----------------------------------------------------------------------
  8/8 checks passed
  READY for live drill. Run: make live-drill
======================================================================
```

Each FAIL line tells you exactly what to fix. Run `make preflight` again
after any change until 8/8.

---

## 4. Upload the cloud-init template (one-time)

This step is **only needed once per base OS** (per template name). After
the template exists, every drill clones from it; you never touch it
again.

### 4a. Boot the template-install VM

```bash
make upload-template NAME=tpl-debian-cloudinit ISO=local:iso/debian-13.4.0-amd64-netinst.iso
```

The script will:

1. Verify the ISO exists on PVE
2. Allocate a free VMID (typically 9000)
3. Create a VM with:
   - 20 GB disk on `local-lvm`
   - 2 GB RAM, 2 vCPUs
   - scsi0 for disk, ide2 for cloud-init, ide3 for ISO
   - boot order: scsi0, then ide3 (the ISO)
4. Set `template=1` immediately (PVE will refuse to boot a template, so
   we'll unset it manually via PVE GUI before installing)

**Wait — there's a subtlety.** The script currently sets `template=1`
unconditionally. You need to:

1. Open PVE GUI → find the new VM (e.g. 9000)
2. **Unset "Template" checkbox** in the VM Options tab (right-click → Options → Template → No)
3. Start the VM → Console
4. Walk through the Debian installer

### 4b. Install Debian

In the VM console:

- Hostname: anything (e.g. `tpl-debian`)
- Network: **DHCP** (the cloud-init drive will rewrite this on every clone)
- Partitioning: **use entire disk**, single partition
- Software selection: **just `SSH server`** + standard system utilities. No desktop, no web server.
- After the installer finishes and prompts to reboot, **shut down** instead:

```bash
sudo shutdown -h now
```

### 4c. Install `qemu-guest-agent` BEFORE shutdown

This is the most-skipped step. Without `qemu-guest-agent`, the runner
can't get the VM's IP, so the win-condition "drill_vm IP is reported"
fails.

If the VM is already booted in step 4b and you've already installed the
OS, you can install the agent post-install:

```bash
sudo apt update
sudo apt install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
sudo shutdown -h now
```

### 4d. Convert to template

After the VM is shut down, return to the dev box:

```bash
make upload-template NAME=tpl-debian-cloudinit   # idempotent if already a template
```

If the script reports the VM is already a template, you're done.

If you need to manually convert (e.g. you re-installed the OS), find
the VMID and:

```bash
python3 tools/upload_cloudinit_template.py --convert-only 9000
```

### 4e. Verify via API

```bash
curl -s http://localhost:8000/api/v1/proxmox/templates | python3 -m json.tool
```

**Expected:**

```json
{
  "items": [
    {"name": "tpl-debian-cloudinit", "vmid": 9000, "node": "pve", ...}
  ]
}
```

---

## 5. Run the live drill

```bash
make live-drill SCENARIO=first-live-drill TIMEOUT=300
```

This runs `tools/live_drill.py` inside the API container. It will:

1. Health-check the API
2. Sync scenarios from YAML into the DB (idempotent)
3. POST `/api/v1/drills` with `{"scenario_id": 3}` (the first-live-drill id)
4. Poll every 2s for terminal status
5. Print the final Run + per-asset status

**Expected output (success):**

```
OK: API {'status': 'ok', 'version': '0.1.0', 'env': 'dev'}
OK: 3 scenarios in catalog:
  - first-live-drill                      id=3
  - lateral-movement-baseline             id=1
  - phish-to-ransom                       id=2
OK: 7 recent runs
  - run id=7    status=failed      scenario_id=1
  ...
-> starting drill: first-live-drill (id=3)
{
  "run_id": 8,
  "status": "pending"
}
-> waiting for run 8 (timeout 300s)...
[  2s left] run=8 status=running    assets=1
[  5s left] run=8 status=running    assets=1
...
[ 80s left] run=8 status=running    assets=1
[ 95s left] run=8 status=running    assets=1
-> final state:
{
  "run_id": 8,
  "status": "succeeded",
  "duration_sec": 87.3
}
```

**Expected output (failure):**

If you see `status: "failed"`, scroll up — the runner logs the exact
PVE error. Most common:

- `403 / Permission denied` → ACL grant didn't take, re-run step 1
- `404 template 'tpl-debian-cloudinit'` → template not uploaded, re-do step 4
- `timeout cloning` → PVE storage full or NFS glitch; check PVE GUI task log

---

## 6. Verify via Grafana

While the drill is running (or right after), open:

- **Grafana dashboard:** http://localhost:3000/d/divide-drill-platform
- **Prometheus expression browser:** http://localhost:9090

**What you should see:**

| Panel | What it shows after a successful drill |
|---|---|
| 1 (Run rate by outcome) | `started` line spikes, then `succeeded` line spikes ~60-120s later |
| 2 (Active runs) | Briefly non-zero during the drill, back to 0 after |
| 3 (Cancel requests donut) | Empty (no cancel was issued) — try `make live-cancel` to populate |
| 4 (HTTP request latency) | p50/p95/p99 in the millisecond range |
| 5 (HTTP request rate by status) | Mostly 200s + a few 4xxs from health checks |
| 6 (Heatmap) | Latency distribution per bucket |

**Useful PromQL queries:**

```promql
# Total drill runs ever (across all outcomes)
sum(divide_runs_total)

# Last successful run's start vs end
divide_runs_total{outcome="succeeded"}

# Active runs right now
divide_runs_active

# Adapter call error rate
sum by (method) (rate(divide_adapter_calls_total{outcome="error"}[5m]))

# API 5xx rate
sum(rate(divide_http_requests_total{status=~"5.."}[5m]))
```

---

## 7. Cancel-mid-flight (optional)

To verify the cancel endpoint works against live PVE:

```bash
make live-cancel SCENARIO=first-live-drill CANCEL_AFTER=30
```

This:

1. POSTs `/api/v1/drills` (within the API container)
2. After 30 seconds, POSTs `/api/v1/drills/{id}/cancel`
3. Waits for the run to reach `cancelled`
4. Prints the final state

**Expected output:**

```
1) starting drill...
-> starting drill: first-live-drill (id=3)
{"run_id": 9, "status": "pending"}
2) watching + cancelling after 30s...
[t+0s] waiting for outcome='cancelled' (cancel armed)
[t+30s] cancel -> HTTP 200: {'run_id': 9, 'status': 'cancelling', ...}

SUCCESS: divide_runs_total{outcome='cancelled'} moved 0.0 -> 1.0 after 47.2s
```

In Grafana, Panel 3 (Cancel requests donut) should now show `ok=1`.

---

## 8. Cleanup (optional)

After a successful drill, the clone VM is left **running**. If you want
to clean it up:

```bash
make live-drill SCENARIO=first-live-drill   # re-run; runner stops + destroys
```

Or manually:

```bash
# Find the asset VMID
curl -s http://localhost:8000/api/v1/drills | python3 -c "
import sys, json
for r in json.load(sys.stdin)['items']:
    print(f"run {r['run_id']}: {r['status']}, scenario_id={r['scenario_id']}")
"

# Stop + destroy via PVE
ssh root@pve "pct stop 9101; pct destroy 9101"   # replace 9101 with the actual VMID
```

The runner's `_best_effort_teardown` already destroys the clone on
`stop_run` / `cancel_run`, so manual cleanup is rarely needed.

---

## Troubleshooting matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| preflight: PROXMOX check FAILs with 503 | PROXMOX_HOST empty | Set in `deploy/.env`, then `docker compose up -d api` |
| preflight: Template check FAILs | Template not uploaded | Run step 4 (upload-template) |
| preflight: PVE nodes check FAILs | Auth/network issue | Test from dev box: `curl -k https://<pve>:8006/api2/json/nodes -H "Authorization: PVEAPIToken=divide@pve@pam!drill-token=<secret>"` |
| live-drill: 403 from PVE | PVEVMAdmin not granted | Re-run step 1 |
| live-drill: template not found (404) | Template uploaded but not visible | Wait 30s for PVE cache, or check `GET /api/v1/proxmox/templates` |
| live-drill: clone timeout | Storage full or NFS issue | Check PVE GUI task log for the clone |
| live-drill: VM boots but no IP in audit | `qemu-guest-agent` not installed | Re-do step 4c, then re-convert template |
| Grafana: no data in panels | Prometheus not scraping | Check `http://localhost:9090/targets` |
| Grafana: dashboard 404 | Provisioning not mounted | `docker compose exec grafana ls /etc/grafana/provisioning/dashboards/` |

---

## Related files

| File | Purpose |
|---|---|
| `tools/preflight.py` | The pre-flight gate (this runbook's source of truth) |
| `tools/live_drill.py` | Runs a drill end-to-end and polls to completion |
| `tools/watch_drill.py` | Companion watcher that exits when a counter moves |
| `tools/upload_cloudinit_template.py` | One-shot template installer |
| `docs/PROXMOX-SETUP.md` | Initial PVE config (token user, ACL) |
| `docs/OBSERVABILITY.md` | Metric reference + Grafana dashboard authoring |
| `deploy/prometheus/prometheus.yml` | Scrape config |
| `deploy/grafana/dashboards/divide-drill-platform.json` | The 6-panel dashboard |
