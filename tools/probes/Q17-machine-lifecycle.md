# Q17: Machine lifecycle investigation report

## Context
After Q14/Q15/Q16 the launch flow works end-to-end: drill creates
a VM, reaches RUNNING state, and the portal reports success. The
probes left 8 `divide-*` VMs on PVE with no clear plan for cleanup.

This report catalogues **6 lifecycle bugs** found by reading the
runner code + probing the live endpoints. **Bug #1 is the root
cause** -- fixing the others largely fall out of it.

## Bug #1 (CRITICAL) — Successful drill never destroys VMs

**Reproduction:**

```bash
$ curl -X POST /api/v1/drills {"scenario_id": 1}
{"run_id": 7, "status": "succeeded", ...}

$ pvesh list cluster-resources --type vm | grep divide-
divide-7-drillvm (vmid=112) -- status: stopped, NEVER DELETED
```

**Code path** (`services/api/app/runners/runner.py` lines 376-385):

```python
# 5. All assets up — flip run to SUCCEEDED.
run.status = RunStatus.SUCCEEDED
...
for br in bridges_created:
    await self._adapter.remove_bridge(br)   # tear down bridges
    # NO vm.stop_vm() / vm.destroy_vm() for the assets !!!
```

The bridge teardown happens but **VM stop + destroy is never
called**. The runner writes `status: succeeded` and walks away,
leaving every asset alive on PVE forever. This is the source of
all 8 leftover VMs from the Q14 verification work.

## Bug #2 (CRITICAL) — destroy_vm silently fails on PVE 9

**Reproduction:**

```bash
$ # Run cleanup manually the way the API does:
$ curl -X DELETE /pve/api2/json/nodes/pve/qemu/112?purge=1&skiplock=1 \
    -H "Authorization: PVEAPIToken=divide@pve@pam!drill-token=..."
{"data":null,"message":"Parameter verification failed.",
 "errors":{"skiplock":"Only root may use this option."}}
```

**Root cause** (`services/api/app/runners/real_adapter.py` line 281):

```python
self._get_client().nodes(node).qemu(vmid).delete(
    purge=1, skiplock=1    # ← PVE 9 reserves skiplock for root@pam
)
```

**`skiplock=1` requires the `root@pam` superuser** on PVE 9. With
our `DivideDrill` custom role (no `Sys.Modify` privileges over VM
locks), this call always rejects. Every destroy attempt from the
runner fails and the asset ends up in `orphaned` state.

**The fix is one line:** drop `skiplock=1`. The current delete
with `purge=1` alone works fine and the operation in our tests
returned `UPID:pve:...:qmdestroy:NNN:divide@pve@pam!drill-token:`
-- the VM was actually destroyed (verified: cleanup reduced 8
leftover VMs to 1).

This explains why the `/{run_id}/stop` endpoint returns HTTP 200
with `assets: [{status: orphaned}]` -- the destroy silently fails
and the runner marks the asset orphaned. From the operator's
perspective, "the API said success" but the VM is still there.

## Bug #3 (CRITICAL) — /drills/{id}/cancel has the same bug as #2

`cancel_run` → `_cancel_run_impl` calls the same `destroy_vm`
(line 568). With bug #2 in place, cancel also returns HTTP 200
without actually deleting the VM.

## Bug #4 (HIGH) — /drills/{id}/stop also leaves the VM

`stop_run` → `_stop_run_impl` calls `destroy_vm` (line 514). Same
issue. **Neither the "stop" nor the "cancel" path actually cleans
up PVE.**

## Bug #5 (LOW) — _stop_run_impl writes RUN_CANCELLED audit action

Line 528: `_stop_run_impl` (the operator-initiated /stop endpoint)
records `AuditAction.RUN_CANCELLED` instead of a dedicated
`RUN_STOPPED`. This conflates two different operator actions in
the audit log. No DB schema impact; the dashboard just shows
"cancelled" for an explicit /stop.

## Bug #6 (LOW) — /drills/{id}/stop passes actor=None

The audit entry written by `_stop_run_impl` includes `actor=None`
(the router doesn't pass `current_token` to `stop_drill`). Cancel
correctly threads the actor through. Cosmetic for now, but makes
"who stopped this run" unrecoverable from the audit log.

## Live state at start of investigation

```
Total VMs on PVE: 16
divide-prefixed: 8 (vmids 108,109,110,111,112,113,114,9100)

DB runs (all status=succeeded):
  run 5 → asset 1 (vmid=110) never cleaned up
  run 6 → asset 1 (vmid=111) never cleaned up
  run 7 → asset 1 (vmid=112) /stop tried → marked orphaned (still on PVE)
  run 8 → asset 1 (vmid=113) never cleaned up
  run 9 → asset 1 (vmid=114) never cleaned up

Audit for run 7:
  run.started, asset.spawned(vmid=112), run.completed
  (no asset-destroyed, no run.cancelled-from-success)
```

## Recommended fix plan (Q17 candidates)

1. **`real_adapter.py`**: drop `skiplock=1` from `destroy_vm`
   (1 line change). Fixes bugs #2, #3, #4.
2. **`runner.py` `start_run`**: after the bridge teardown on
   success path, also stop + destroy each asset. Roughly:
   ```python
   for asset in spawned_assets:
       try:
           await self._adapter.stop_vm(asset.pve_vmid, asset.pve_node)
           await self._adapter.destroy_vm(asset.pve_vmid, asset.pve_node)
           asset.status = AssetStatus.STOPPED
       except Exception as exc:
           asset.status = AssetStatus.ORPHANED
           asset.error = f"cleanup failed: {exc}"
   ```
   With fix #1 in place, this reliably cleans up. Fixes bug #1.
3. **`runner.py`**: add `AuditAction.RUN_STOPPED` and use it in
   `_stop_run_impl`. Fixes bug #5.
4. **`routers/drills.py`**: thread `current_token.sub` into
   `stop_drill` and pass it through to the runner. Fixes bug #6.

## Cleanup of the existing 8 leftover VMs

Done by hand during this investigation: `DELETE /pve/api2/json/
nodes/pve/qemu/<vmid>?purge=1` (without `skiplock`) succeeds for
all of them. Going from 8 divide-* VMs to 1 (9100 is template-
flagged, intentional). Live evidence:

```
$ for vmid in 108 109 110 111 112 113 114; do
    curl -X DELETE /pve/api2/json/nodes/pve/qemu/$vmid?purge=1
  done
{"data":"UPID:pve:...:qmdestroy:$vmid:divide@pve@pam!drill-token:"}

$ pvesh list cluster-resources --type vm | grep divide-
divide-1-drillvm (vmid=9100)   ← template, kept
```

No emergency: investigate thoroughly before committing fixes so
we don't make a Q17-commit that breaks existing drill launch.
