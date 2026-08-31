# F3 Runbook — Bridge Provisioning on Proxmox VE

> **Status:** F3 shipped (`2a97525` + `6e9e5b5`). The runner now iterates (✅ shipped; see [PLAN.md §15.6](PLAN.md) for the full §15 closure summary.)
> `spec.networks[]` and `spec.assets[].networks[]`, creating one Linux
> bridge per network declaration and attaching NICs to each asset.
>
> **Audience:** Proxmox operators who own the network plumbing. The
> runner does the API-level orchestration; you do the OS-level
> plumbing on each PVE node.
>
> **F-pve-bridge-wizard (SDN variant, 2026-08):** the first-time
> portal wizard now has a Step 0 that drives PVE's Software-Defined
> Networking API to create the Linux bridges for you -- no SSH, no
> editing `/etc/network/interfaces`, no `ifreload`. The CLI escape
> hatch is `pvesh` against `/cluster/sdn/{zones,vnets}`. The
> manual steps in this runbook are still the source of truth -- the
> wizard just automates them via a different API path.

## TL;DR

**Default path:** open the portal → first-time wizard Step 0
auto-provisions everything via PVE SDN. The CLI escape hatch is:

```bash
# One-time: create the div:ide zone on the cluster
pvesh create /cluster/sdn/zones -zone divide -type simple -bridge vmbr0

# Per scenario network: create a VNet (= one Linux bridge per node)
pvesh create /cluster/sdn/vnets -vnet vmbr100 -zone divide

# Confirm the bridge landed on the node
pvesh get /nodes/pve/network | jq '.data[] | select(.iface=="vmbr100")'
```

**Manual path** (when you can't or don't want to use the wizard):

```bash
# On every PVE node that will host a cyber-range drill:
# 1. Reserve a contiguous range of vmbrN IDs that the runner can use.
#    The runner auto-allocates vmbr100, vmbr101, … from F3 onwards;
#    avoid using those IDs for operator-managed bridges.
# 2. For each network declared in a scenario, create a vmbrN on the
#    node the drill will run on, with the right CIDR + isolation.
# 3. Reload networking so the bridge is live.
```

## Why this needs a runbook

**PVE does not expose a public bridge-creation API.** The Proxmox VE
platform has no public API for creating Linux bridges on nodes — bridge
configuration lives in `/etc/network/interfaces` and is managed by the
operator. This is why the runner cannot auto-create bridges and must
assert they exist instead.

Bridges are managed via PVE's Software-Defined Networking stack
(PVE 8.1+ / PVE 9): the runner no longer creates them through
SSH or by editing `/etc/network/interfaces`. Instead, the wizard's
Step 0 (or `POST /api/v1/admin/pve-setup-bridges`) creates a
Simple zone named `divide` plus one VNet per declared network via
`POST /cluster/sdn/{zones,vnets}`. PVE auto-propagates the
resulting Linux bridges to every node in the cluster.

The runner's role shrinks to *assertion + best-effort cleanup*:

- **Runner surface:** `RealProxmoxAdapter.create_bridge(spec)` asserts
  that the bridge already exists on the target node by calling
  `GET /nodes/{node}/network` and looking for `iface == <bridge>`.
  If the bridge is missing, the call raises `ProxmoxAPIError`
  with an actionable message: the operator must re-run the
  wizard's Step 0 (or `pvesh create /cluster/sdn/vnets -vnet
  <name> -zone divide`). The error message names both paths
  and points at `docs/PROXMOX-SETUP.md §4` for the full
  SDN flow.

- **Runner surface:** `RealProxmoxAdapter.remove_bridge(bridge)`
  issues `DELETE /cluster/sdn/vnets/{bridge}` as best-effort
  cleanup so a failed drill doesn't leave orphan Vnets
  accumulating on the cluster. Errors are logged and swallowed --
  a transient PVE failure during teardown should never break an
  otherwise-successful drill. The adapter's idempotency makes
  retries safe.

- **Mock surface:** the in-memory mock calls `create_bridge` /
  `remove_bridge` faithfully; tests assert that bridges are created
  in number-and-naming and torn down on success + failure paths.

## Bridge allocation scheme

| Range | Owner | Notes |
|---|---|---|
| `vmbr0` … `vmbr99` | Operator | Pre-existing PVE bridge names (default cluster mgmt + storage). Don't reuse. |
| `vmbr100` … `vmbr16383` | F3 runner | Allocated sequentially per run, starting at `vmbr100`. Each `spec.networks[]` declaration consumes one ID. The lifecycle is per-run: created at run-start, torn down at run-end (best-effort). |

If the operator manages a cyber range that anticipates >16k concurrent
drills, please open an issue — we'll bump the allocation floor.

## Concrete setup steps (single-node PVE)

This is the smallest reproducible setup. For multi-node, see §5.

### 1. Pick a node

The runner operates on one node per drill (currently; multi-node is
F3-followup territory). Use `pvecm status` to see your cluster; pick
the node that has the templates. We'll call it `pve`.

### 2. Add the bridges

For each scenario `spec.networks[]` entry, create a VNet in the
`divide` SDN zone (or add a stanza to `/etc/network/interfaces` for
the legacy non-SDN path; PVE treats both identically):

**SDN path (PVE 8.1+ / PVE 9 — preferred):**

```bash
# Replace vmbr100 with whichever F3-allocated bridge the runner will
# call create_bridge() with. The runner uses vmbr100, vmbr101, …
# starting from 100 per declared network.

# One-time: create the div:ide zone on the cluster.
pvesh create /cluster/sdn/zones -zone divide -type simple -bridge vmbr0

# Per network: create a VNet (one Linux bridge per node on the cluster).
pvesh create /cluster/sdn/vnets -vnet vmbr100 -zone divide

# Verify the bridge landed on the node.
pvesh get /nodes/pve/network | jq '.data[] | select(.iface=="vmbr100")'
```

PVE 8.1+ ships the SDN controller by default; PVE 9 always has it.
No additional package install is needed.

**Legacy path (PVE ≤ 8.0 or non-SDN clusters):**

```bash
# For each scenario spec.networks[] entry, add a stanza to
# /etc/network/interfaces (or /etc/network/interfaces.d/divide.conf):
auto vmbr100
iface vmbr100 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    # Tight isolation blocks all but router-traffic between this
    # bridge and other vmbrs (no ip_forward by default).
    post-up   iptables -A FORWARD -i vmbr100 -j DROP
    post-down iptables -D FORWARD -i vmbr100 -j DROP

# Reload without dropping the SSH session.
ifreload -a

# Verify the bridge exists.
ip link show vmbr100   # Should show: state UP
```

The legacy path is still supported for older PVE installs where SDN
isn't available, but new deployments should use SDN — it's purely
API-driven, requires no SSH access, and survives PVE upgrades.

### 3. Whitelist the bridge with the API

The API server's egress firewall (if any) must let `pve` listen on
the bridge subnet. Otherwise PVE can't talk to cloned VMs when
they boot. Add the bridge subnet to your API egress rules:

```bash
# Example for an nftables-managed host:
nft add rule inet divide-api-output ip daddr 10.10.10.0/24 accept
```

### 4. Repeat for each scenario

Each `spec.networks[]` declaration needs one `vmbrN` entry. The
**scenario** `red-vs-blue-baseline` (commit `a76f4ee`) declares
three networks; you'd add three bridge stanzas:

- `vmbr100` — red_vlan, CIDR 10.10.10.0/24
- `vmbr101` — dmz, CIDR 10.10.20.0/24
- `vmbr102` — blue_vlan, CIDR 10.10.30.0/24

The runner allocates sequentially so the third `spec.networks[]`
maps to `vmbr102`. **Don't hard-code** "red is vmbr100"; that
breaks the moment you add a network to the YAML. Always allocate
based on `vmbr100+offset`.

### 5. Multi-node PVE (advanced)

The runner currently expects one node per drill; multi-node is
deferred. For now, all the bridges for a single scenario must
live on the same node. If the templates are scattered, use a
`divide-target` annotation in your Ansible inventory to colocate
the bridges and templates.

When F3-followup ships multi-node, this section will describe
the per-node bridge naming + the requirement that every node
in the drill's got `vmbrN+offset` for every declared network.

## What can go wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Drill fails with `bridge vmbr100 not configured on PVE node pve` | SDN VNet for `vmbr100` missing on the target node | Re-run the wizard's Step 0 (or `pvesh create /cluster/sdn/vnets -vnet vmbr100 -zone divide`). See `docs/PROXMOX-SETUP.md §4`. |
| Bridges exist but cloned VMs have no IP | `bridge-ports none` is wrong (the bridge has no slave) | That's the correct setting if no physical NIC is attached; verify cloud-init is reaching the metadata server |
| Bridges exist; cloned VMs can't reach the gateway | `iptables -A FORWARD -i vmbr100 -j DROP` blocks inter-vm traffic that the topology needs | Add `-A FORWARD -i vmbr100 -o vmbr101 -j ACCEPT` for the router bridge pair; or remove the rule entirely (operator-managed ranges shouldn't have it) |
| /api/v1/drills returns 500 with `Network ...` error | Runner sees the YAML but loses network metadata | Validate the YAML against the scenario schema (`validate-scenarios` Make target); ensure the JSON parses without additionalProperties: false violations |
| Drill hangs at `attaching NIC to vmbrN` | Real-adapter create_bridge succeeded but the bridge is actually a different vmbrN than the runner is asking for | Check that no operator-created vmbrN collides with the F3 allocation range; use `pvesh get /nodes/pve/network --output-format json` to list |

## Testing the bridge plan locally

If you want to verify the runner's intent before running it on PVE,
use the mock adapter in a local docker-compose stack:

```bash
# 1. Don't set PROXMOX_HOST and friends; the runner auto-falls
#    back to MockProxmoxAdapter. The mock has no real network
#    state but it records every create_bridge / attach_network
#    call for assertions.
make up
# 2. POST /api/v1/drills with body {"scenario": "red-vs-blue-baseline"}.
# 3. Watch the run logs: every line starting with `runner.networks`
#    is the F3 surface. `bridge_created name=red_vlan bridge=vmbr100`
#    means the runner planned to attach red_vlan's VMs to vmbr100.
# 4. Make sure the real PVE matches.
```

The cyber-range demo scenario (`red-vs-blue-baseline`) renders this
loop in code:

```
spec.networks[0] -> bridge vmbr100 -> red_attacker.attached(red_vlan)
spec.networks[1] -> bridge vmbr101 -> (no asset)
spec.networks[2] -> bridge vmbr102 -> router_fw.attached(blue_vlan),
                                       victim_workstation.attached(blue_vlan),
                                       file_server.attached(blue_vlan),
                                       log_aggregator.attached(blue_vlan)
```

If you've prepared three bridges and they all exist on the target
node, the drill proceeds past the network-setup phase and the
adapter's `attach_network` calls succeed.

## See also

- [`docs/DEMO.md`](DEMO.md) — the operator's "show me the cyber
  range in 5 minutes" guide
- [`docs/PROXMOX-SETUP.md`](PROXMOX-SETUP.md) — pre-F3 PVE setup
  (token, templates, ACLs). The bridge work in this doc is
  additional to that setup.
- [`docs/PLAN.md`](PLAN.md) §15 — the cyber-range roadmap. F4
  (noVNC) and F6 (multi-team) build on F3's topology.
- [`schemas/scenario.schema.json`](../schemas/scenario.schema.json)
  — the JSON schema that pins every `networks[]` declaration.
  Run `make validate-scenarios` to confirm your YAML matches.
