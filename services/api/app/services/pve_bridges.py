"""PVE bridge planner + SDN-backed applier.

The F3 runner auto-allocates ``vmbr100``, ``vmbr101``, ... per
scenario ``spec.networks[]`` declaration and
``RealProxmoxAdapter.create_bridge`` asserts each one already
exists. PVE historically had no public API to *create* Linux bridges
-- they lived in ``/etc/network/interfaces`` (or
``/etc/network/interfaces.d/``) and were activated by ``ifreload -a``,
which required SSH + sudo on the PVE host.

That changed with PVE 8.1's Software-Defined Networking (SDN) stack:
``POST /cluster/sdn/{zones,vnets}`` creates Linux bridges purely via
the API, and PVE propagates them to each node automatically. We use
that path -- see ``services/pve_sdn.py`` for the API layer.

This module is responsible for the *planning* half of that work:

  * :func:`plan_bridges`  -- pure planner. Reads the DB
     scenarios and returns the list of bridges that *should*
     exist on the PVE node. No network calls.
  * :func:`plan_bridges_from_db` -- DB-backed wrapper around the
     above.
  * :func:`fetch_present_bridges` -- reads the PVE API
     (``/nodes/{node}/network``) and returns the set of bridge
     ifaces that already exist. Used by the wizard to decide
     whether Step 0 is needed at all.

The applier half lives in :mod:`app.services.pve_sdn` and uses the
SDN API instead of SSH. The wizard's Step 0 (formerly an SSH-form)
is now a single button that POSTs to ``/api/v1/admin/pve-setup-bridges``
with no body -- the API uses the credentials already saved in Step -1
to create the SDN zone + Vnets.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# --- constants ------------------------------------------------------------

#: vmbrN the runner auto-allocates from. F3-RUNBOOK documents this
#: range; changing it is a breaking change for any existing scripts.
BRIDGE_START: int = 100


# --- exceptions -----------------------------------------------------------


class BridgePlanError(Exception):
    """The planner couldn't produce a valid bridge list."""


class PveSshError(Exception):
    """Deprecated: the SSH-based applier has been removed in favor of PVE SDN.

    Kept as an import-shim so out-of-tree callers don't crash. New code
    should not raise or catch this; use ``app.services.pve_sdn.SdnError``.
    """


# --- data shapes ----------------------------------------------------------


@dataclass(frozen=True)
class BridgeSpec:
    """One bridge the runner expects on the PVE host.

    ``name`` is the iface name (e.g. ``vmbr100``); ``cidr`` is
    the declared scenario CIDR; ``scenario`` is the scenario
    that contributed it (for surfacing in the UI).
    ``gateway_ip`` is the host address the bridge uses for its
    own iface.
    """

    name: str
    cidr: str
    gateway_ip: str
    scenario: str
    network: str

    @property
    def stanza(self) -> str:
        """Render the interfaces.d stanza for this bridge."""
        prefix = _cidr_prefixlen(self.cidr)
        return (
            f"auto {self.name}\n"
            f"iface {self.name} inet static\n"
            f"    address {self.gateway_ip}/{prefix}\n"
            f"    bridge-ports none\n"
            f"    bridge-stp off\n"
            f"    bridge-fd 0\n"
            # Tight isolation per F3-RUNBOOK §2: blocks inter-vm
            # traffic between this bridge and others. Operators
            # can edit the drop-in to relax this for
            # router-traffic pairs (see F3-RUNBOOK "What can go
            # wrong" table).
            f"    post-up   iptables -A FORWARD -i {self.name} -j DROP\n"
            f"    post-down iptables -D FORWARD -i {self.name} -j DROP\n"
        )


@dataclass(frozen=True)
class BridgePlan:
    """Output of :func:`plan_bridges`."""

    bridges: list[BridgeSpec]
    conflicts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApplyResult:
    """Output of :func:`apply_bridges`."""

    added: list[str]
    already_present: list[str]
    reload_ok: bool
    reload_method: str
    verify_ok: bool
    config_path: str

    @property
    def ok(self) -> bool:
        """Convenience: True iff reload AND verify succeeded."""
        return self.reload_ok and self.verify_ok


# --- planner (pure, no I/O) ----------------------------------------------


def plan_bridges(scenarios: Iterable[dict]) -> BridgePlan:
    """Compute the dedup'd set of bridges the runner expects.

    Allocation scheme: each unique ``(scenario, network_name)`` pair
    gets its own ``vmbr{BRIDGE_START + idx}``, where ``idx`` is the
    pair's position in a sorted, dedup'd enumeration of all pairs
    across all scenarios. This guarantees no two scenarios share a
    bridge unless they explicitly declare the same network name.

    Why per-(scenario, network) instead of per-scenario:
        The old naive scheme allocated ``vmbr100`` to each scenario's
        first network, which collided when two scenarios both
        declared a single network with different CIDRs (e.g.
        ``first-live-drill`` uses 10.50.0.0/24 but
        ``phish-to-ransom`` uses 10.50.50.0/24 for its first
        network). Per-pair allocation matches the F3 runner's
        semantics -- the runner clones one VM per asset per
        scenario, and each asset attaches to its scenario's
        networks -- and avoids those collisions.
    """
    # Step 1: collect all (scenario, network_name, cidr) triples,
    # in deterministic order.
    triples: list[tuple[str, str, str]] = []
    for scenario in scenarios:
        name = (
            scenario.get("name")
            or scenario.get("metadata", {}).get("name")
            or "?"
        )
        # DB stores the whole YAML body under ``spec``; the body
        # itself has ``spec: { ... networks: [...] }``. We accept
        # both shapes (DB rows + /scenarios output) for callers.
        outer = scenario.get("spec") or {}
        inner = (
            outer.get("spec")
            if isinstance(outer.get("spec"), dict)
            else outer
        )
        networks = inner.get("networks") or []
        for offset, net in enumerate(networks):
            cidr = net.get("cidr")
            net_name = net.get("name") or f"network_{offset}"
            if not cidr:
                log.warning(
                    "pve_bridges.skip_network_no_cidr",
                    scenario=name,
                    network=net_name,
                )
                continue
            triples.append((name, net_name, cidr))

    # Step 2: dedup. Two scenarios that share a network_name
    # intentionally want the one bridge (e.g. two scenarios
    # both declare ``corp_vlan`` on the same CIDR -- one
    # bridge suffices). Two scenarios that use different CIDRs
    # under the same network_name is a config bug; we surface
    # it as a conflict.
    by_key: dict[tuple[str, str], str] = {}  # (scenario, net_name) -> cidr
    by_bridge: dict[str, BridgeSpec] = {}
    used_cidrs: list[tuple[str, str]] = []
    conflicts: list[str] = []

    triples_sorted = sorted(triples, key=lambda t: (t[0], t[1]))
    for idx, (scenario, net_name, cidr) in enumerate(triples_sorted):
        bridge_name = f"vmbr{BRIDGE_START + idx}"
        # Check if another scenario already declared the same
        # (network_name, cidr) -- if so, that's the same bridge.
        dup_key = None
        for (s2, n2), existing_cidr in by_key.items():
            if s2 != scenario and n2 == net_name and existing_cidr == cidr:
                dup_key = (s2, n2)
                break
        if dup_key is not None:
            # Another scenario already has this exact (name, cidr).
            # Re-use its bridge name.
            existing_bridge = next(
                b for b in by_bridge.values()
                if b.scenario == dup_key[0] and b.network == dup_key[1]
            )
            bridge_name = existing_bridge.name
        else:
            # New bridge. Check that no other bridge has the same
            # name with a different CIDR.
            if bridge_name in by_bridge:
                existing = by_bridge[bridge_name]
                if existing.cidr != cidr:
                    # Two scenarios, same slot, different CIDR.
                    # Resolve by re-allocating to a fresh slot.
                    # (Conflicts below will catch the upstream bug.)
                    conflicts.append(
                        f"bridge {bridge_name}: scenario {scenario!r} "
                        f"network {net_name!r} declares CIDR {cidr}, "
                        f"but scenario {existing.scenario!r} network "
                        f"{existing.network!r} already uses "
                        f"{existing.cidr}"
                    )
        try:
            gateway_ip = _first_host_ip(cidr)
        except ValueError as exc:
            raise BridgePlanError(
                f"scenario {scenario!r}: invalid CIDR {cidr!r}: {exc}"
            ) from exc
        spec_obj = BridgeSpec(
            name=bridge_name,
            cidr=cidr,
            gateway_ip=gateway_ip,
            scenario=scenario,
            network=net_name,
        )
        if bridge_name not in by_bridge:
            by_bridge[bridge_name] = spec_obj
            used_cidrs.append((cidr, bridge_name))
            by_key[(scenario, net_name)] = cidr

    for i, (cidr_a, name_a) in enumerate(used_cidrs):
        for cidr_b, name_b in used_cidrs[i + 1 :]:
            if _cidrs_overlap(cidr_a, cidr_b):
                conflicts.append(
                    f"CIDR overlap: {name_a}={cidr_a} overlaps "
                    f"{name_b}={cidr_b}"
                )

    return BridgePlan(
        bridges=sorted(by_bridge.values(), key=lambda b: int(b.name[4:])),
        conflicts=conflicts,
    )


async def plan_bridges_from_db(session: AsyncSession) -> BridgePlan:
    """Read scenarios from the DB and return the plan."""
    from app.db import models as db_models
    from sqlalchemy import select

    rows = (
        await session.execute(
            select(db_models.Scenario).where(
                db_models.Scenario.archived_at.is_(None)
            )
        )
    ).scalars().all()
    scenario_dicts = [
        {
            "name": r.name,
            "spec": r.spec,
            "metadata": {"name": r.name},
        }
        for r in rows
    ]
    return plan_bridges(scenario_dicts)


# --- read-only PVE queries (no SSH) ---------------------------------------


async def fetch_present_bridges(node: str) -> set[str]:
    """Read ``/nodes/{node}/network`` and return the bridge ifaces.

    Read-only; uses the existing PROXMOX_* token (no SSH).
    Returns an empty set if PVE is unreachable or unconfigured
    so the wizard can still proceed to SSH-setup.
    """
    import os

    import httpx

    base = os.environ.get("PROXMOX_HOST", "").rstrip("/")
    if not base:
        return set()
    port = int(os.environ.get("PROXMOX_PORT", "8006"))
    tok = os.environ.get("PROXMOX_TOKEN_ID", "")
    sec = os.environ.get("PROXMOX_TOKEN_SECRET", "")
    verify = os.environ.get("PROXMOX_VERIFY_SSL", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    url = f"{base}:{port}/api2/json/nodes/{node}/network"
    try:
        async with httpx.AsyncClient(verify=verify, timeout=5.0) as client:
            r = await client.get(
                url,
                headers={"Authorization": f"PVEAPIToken={tok}={sec}"},
            )
        if r.status_code != 200:
            log.warning(
                "pve_bridges.list_network_failed",
                node=node,
                status=r.status_code,
            )
            return set()
        data = r.json().get("data", []) or []
    except httpx.HTTPError as exc:
        log.warning("pve_bridges.list_network_error", error=str(exc))
        return set()

    bridges: set[str] = set()
    for iface in data:
        iface_type = (iface.get("type") or "").lower()
        if iface_type in ("bridge", "vlan"):
            name = iface.get("iface")
            if name:
                bridges.add(name)
    return bridges


# --- applier (SDN-backed; see services/pve_sdn.py) ------------------------


async def apply_bridges(
    plan: BridgePlan,
    *,
    node: str = "pve",
    dry_run: bool = False,
) -> ApplyResult:
    """Drive the PVE SDN controller to realize the plan.

    Thin wrapper kept for callers that already pass a ``BridgePlan``
    (notably ``POST /admin/pve-setup-bridges`` and the tests). The
    actual implementation lives in :mod:`app.services.pve_sdn`.

    The old SSH-based path (``paramiko`` + ``ifreload -a``) is gone:
    PVE 8.1+ exposes ``/cluster/sdn/{zones,vnets}`` which creates the
    same Linux bridges purely via API. See
    ``docs/PROXMOX-SETUP.md`` for the new permission requirement
    (``SDN.Allocate`` on the PVE token).

    The function signature still accepts ``node=`` for backwards
    compatibility with test fixtures that pre-date the pivot.
    """
    from app.services.pve_sdn import (
        apply_sdn_plan,
        get_active_auth,
        to_apply_result,
    )

    auth = get_active_auth(node=node)
    sdn = await apply_sdn_plan(plan, auth=auth, dry_run=dry_run)
    return to_apply_result(plan, sdn)


# --- helpers --------------------------------------------------------------


def _first_host_ip(cidr: str) -> str:
    """Return the first usable host IP in ``cidr``.

    For ``10.50.0.0/24`` this is ``10.50.0.1``. For ``/31`` and
    ``/32`` the network address itself is returned (those are
    valid for point-to-point).
    """
    net = ipaddress.ip_network(cidr, strict=False)
    if net.num_addresses >= 2:
        return str(net.network_address + 1)
    return str(net.network_address)


def _cidr_prefixlen(cidr: str) -> int:
    """Extract the prefix length as an int.

    Validates the CIDR by attempting to parse it (raises
    ValueError on garbage).
    """
    ipaddress.ip_network(cidr, strict=False)
    return int(cidr.split("/")[1])


def _cidrs_overlap(a: str, b: str) -> bool:
    """True if the two CIDRs share any address."""
    try:
        return ipaddress.ip_network(a, strict=False).overlaps(
            ipaddress.ip_network(b, strict=False)
        )
    except ValueError:
        return False


__all__ = [
    "ApplyResult",
    "BRIDGE_START",
    "BridgePlan",
    "BridgeSpec",
    "BridgePlanError",
    "PveSshError",  # deprecated; see app.services.pve_sdn.SdnError
    "apply_bridges",  # SDN-backed wrapper around apply_sdn_plan
    "fetch_present_bridges",
    "plan_bridges",
    "plan_bridges_from_db",
]