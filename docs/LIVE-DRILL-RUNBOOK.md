# Live Drill Runbook

Step-by-step instructions for executing the first real Proxmox VM clone
end-to-end. Use this whenever you need to (re)verify the platform
against a live PVE host.

> **TL;DR**
>
> 1. `pveum acl modify /v2/vm --users divide@pve@pam --roles PVEVMAdmin` (PVE host shell)
>    _(On PVE 8+/9 the flags are `--users`/`--roles` plural. Older PVE
>    used `--userid`/`--role` — if your `pveum` rejects these, check
>    `pveum acl modify --help` for the right spelling.)_
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
| Token privileges: `PVEVMAdmin` on `/v2/vm` | PVE host | `pveum acl list` (filter for `divide@pve@pam`) |
| Debian netinst ISO uploaded to PVE | PVE GUI | Datacenter → pve → local → ISO Images → Upload |
| Outbound network from dev box to PVE on :8006 | network | `nc -zv <pve> 8006` |

---

## 1. Grant PVEVMAdmin (PVE host shell)

The `divide@pve@pam` user needs PVEVMAdmin on `/v2/vm` to clone,
start, stop, and destroy VMs. Without this, the runner will fail with a
403 from PVE.

```bash
# On the PVE host shell
pveum acl modify /v2/vm --users divide@pve@pam --roles PVEVMAdmin

# Confirm
pveum acl list
```

**Expected output (filtered for the divide user):**

```
~ pveum acl list
┌──────┬────────────┬──────┬────────────────┬───────────┐
│ path │ roleid     │ type │ ugid           │ propagate │
╞══════╪════════════╪══════╪════════════════╪═══════════╡
│ /v2/vm │ PVEVMAdmin │ user │ divide@pve@pam │ 1         │
└──────┴────────────┴──────┴────────────────┴───────────┘
```

(Or, equivalently, `PVEAdmin` on `/` with propagate=1 — broader, also
covers `/v2/vm`. See `docs/PROXMOX-SETUP.md` §8 for the trade-off.)

If you don't see that line, the grant didn't take. Re-run the command.

> **Heads up — PVE version note:** The flags changed in PVE 8. If
> `pveum acl modify` says `Unknown option: userid`, you're on a version
> that uses `--users` (plural) instead. PVE 7 and earlier used
> `--userid` and `--role` (singular). `pveum acl modify --help` shows
> what's accepted on your PVE.

**Troubleshooting:**

- If `pveum` isn't found: you're on the wrong host. SSH to the PVE host.
- If the user doesn't exist: `pveum user add divide@pve@pam --comment "div:ide runner"`
- If the role doesn't exist: `pveum role list | grep PVEVMAdmin` — it should be there by default in PVE 8+.

### 1.5. Verify the ACL via PVE's per-principal permissions API

This is the **one** verification that actually matters. The ACL table
(`pveum acl list`) requires `Access.Audit` which the divide token
deliberately doesn't have — so `pveum` on the dev box will see what the
operator user sees, not what the divide token sees.

Run this from the dev box (uses the divide token):

```bash
curl -sk -H "Authorization: PVEAPIToken=$(grep ^PROXMOX_TOKEN_ID deploy/.env | cut -d= -f2)=$(grep ^PROXMOX_TOKEN_SECRET deploy/.env | cut -d= -f2)" \
  https://$(grep ^PROXMOX_HOST deploy/.env | cut -d= -f2 | sed 's|https://||')/api2/json/access/permissions
```

Expected: a JSON object with a `/` key containing at least
`VM.Allocate`, `VM.Clone`, and `VM.PowerMgmt` (or any subset on
`/vms`, `/v2/vm`, etc.). `preflight` runs this same check.

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

**Expected: 9/9 checks PASS** (1/2 healthz + Proxmox config + nodes
+ ACL + Template + scenario + metrics + Prometheus + Grafana = 9).

```
======================================================================
PRE-FLIGHT REPORT
======================================================================
  [PASS] /healthz responds 200                              env=dev, version=0.1.0
  [PASS] PROXMOX_* configured (RealProxmoxAdapter)          version=9.1.7, ok=?
  [PASS] PVE nodes reachable                                1 node(s): pve
  [PASS] ACL grants PVEVMAdmin on /v2/vm to divide@pve@pam  path=/ privs=VM.Allocate,VM.Clone,VM.PowerMgmt (via /access/permissions)
  [PASS] Template 'tpl-debian-cloudinit' exists on PVE      vmid=9000
  [PASS] Scenario 'first-live-drill' in DB                  id=3
  [PASS] /metrics live on API                               12 divide_* metric families, ...
  [PASS] Prometheus scraping divide-api                     http://api:8000/metrics -> up
  [PASS] Grafana dashboard 'divide-drill-platform' loaded   title='div:ide — Drill Platform', panels=6
----------------------------------------------------------------------
  9/9 checks passed
  READY for live drill. Run: make live-drill
======================================================================
```

If the ACL check fails with "no drill privileges found", see §1.5
below — the fix is on the PVE host, not in the runbook.

If the template check fails, the wizard at `/portal/` (§4b) or the
manual path (§4c–4e) below are both fine — pick whichever you prefer.

Each FAIL line tells you exactly what to fix. Run `make preflight` again
after any change until 9/9.

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

## 8.5. Try it from the user portal

The CLI flow above is the canonical CI path. For human-in-the-loop,
the user portal at `/portal/app/` is now the recommended entry
point.

1. Mint a short-lived token:

   ```bash
   python3 tools/issue_token.py --user alice --role trainee --ttl 1h
   # prints: <token>
   ```

2. Open `http://localhost:8000/portal/app/` in a browser.

3. Paste the token into the top bar. The bar flips to
   `signed in as alice · trainee`.

4. Click any scenario in the **Scenarios** card. Today the run
   lifecycle is still rolling out (next-plan M3.2–M3.7), so for
   actually starting a drill from the portal use the curl form
   below — the rest of the cards are queued in the [next plan](TEST-PRODUCT.md#next-plan-post-l1-ordered).

   ```bash
   # Start a drill (paste scenario_id from the portal click)
   curl -s -X POST http://localhost:8000/api/v1/drills \
     -H "X-Divide-Token: <token>" \
     -H "Content-Type: application/json" \
     -d '{"scenario_id": 3}' | python3 -m json.tool

   # Watch it (returns the new run_id above)
   curl -s http://localhost:8000/api/v1/drills/<run_id> \
     -H "X-Divide-Token: <token>" | python3 -m json.tool
   ```

and `/portal/` (the setup wizard you ran in §4). All three share
the same FastAPI mount under `/portal/`. See [PORTAL-APP.md](PORTAL-APP.md).

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

---

## 9. What's next (post-L1)

L1 closed with run #11 (`status=succeeded`). The five next moves
(from `docs/TEST-PRODUCT.md` §"Next plan") are now:

| # | Item | Status |
|---|---|---|
| 1 | **Cancel-path smoke tests** for `live-cancel` + `watch-drill` via MockProxmoxAdapter | ✅ done (`tests/test_cancel_smoke.py`) |
| 2 | **`make verify` alias** (`lint && test && preflight && smoke`) | ✅ done (commit `be36033`) |
| 3 | **Wire `make verify-drill` into CI** | ✅ done (commit `be36033`) |
| 4 | **Token middleware + `divide issue-token` CLI** | ✅ done (commit `90f7eaa`) |
| 5 | **SSH-key wizard step** (Bucket E) so the wizard flips `PVEDatastoreAdmin` itself | ❌ optional (~1 h) — current stand-in is the wizard's copy-paste `pveum` block |

**Remaining L2 work** (~2.5 h, no PVE required): items 2.7 (rate-limit
on `POST /drills`), 2.8 (drill auto-timeout), 2.11 (MinIO telemetry
sink), 2.12 (after-action JSON report). Once those ship: L2 ledger
15/18 ✅, tag `v0.2.0-l2`.

L3 is a separate project — see [docs/TEST-PRODUCT.md](TEST-PRODUCT.md)
§L3 for the scope.

### Why these five (not others)

These are the items that:

- Close remaining L1 criteria without any PVE work (1, 2, 3) — flip
  5 ❌ → ✅ in 1.5 h.
- Unblock the L2 work in this order (4 → 5 → then everything else).
- Don't depend on each other — could be done one per session.

What we're **not** doing next:

- More Phase 2 work (multi-VM, SDN zones) — that's L3.
- Real auth — that's L2.
- Resilient queue workers — that's Phase 3+.

### Tooling that already exists for the next steps

| Need | Tool |
|---|---|
| Cancel-path coverage | `MockProxmoxAdapter` + `tests/test_runner.py` already cover 70% |
| CI wiring | `.github/workflows/ci.yml` has the slots; just need to add `make verify-drill` |
| Token middleware | `app/core/` is the right home; `app.core.config.settings.proxmox.token_secret` is the model |
| SSH-key for wizard | `docs/SETUP-UI.md` §"When to use the runbook instead" lists what changes |

### What *does* still need PVE work after L1

1. **Updating templates** (new `tpl-kali`, `tpl-win2022`): even with
   the wizard, each new template still needs a base OS image and
   PVE-side network setup.
2. **Real multi-node**: today `tpl-debian-cloudinit` lives on one node.
   Multi-node drills need it replicated.
3. **SDN zones per drill**: Phase 2 work; no PVE token setup tricks
   will get around this.

### Tracking these

L1 ledger lives in [docs/TEST-PRODUCT.md](TEST-PRODUCT.md) §L1 Criteria.
Every time one flips ✅ the doc's update log gets a row.

L2 ledger lives in the same doc §L2; the items in the table above are
2.3, 2.4, 2.5, 2.9, 2.13, 2.14.

L3 is in the same doc §L3 — out of scope for the next move.
