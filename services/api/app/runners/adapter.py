"""Adapter interface between the runner and Proxmox.

Why this exists
---------------
The runner should never speak proxmoxer directly. By defining a small
Protocol-style interface, we can:
  * Test the runner end-to-end with a deterministic in-memory fake.
  * Swap implementations without touching the state machine.
  * Keep the runner's "what to do" separate from "how to talk to PVE".

Real adapter (RealProxmoxAdapter) will land in a later commit, once
PVE auth is fixed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkSpec:
    """Inputs to `create_bridge`.

    A bridge is a PVE Linux bridge (vmbrN) that hosts assets on a
    shared subnet. F3 (multi-VM scenarios) creates one bridge per
    spec.networks[] entry, then attaches each asset to the bridges
    that match the assets' spec.networks[] arrays.

    Attributes:
        bridge: Bridge name on PVE (e.g. ``vmbr42``). Must be unique
                within the cluster; we'll allocate sequentially.
        cidr:   CIDR block, as declared in the scenario YAML
                (informational on real PVE; PVE doesn't strictly
                enforce the CIDR, but we use it for topology planning
                and router IP calculation).
        isolation: 'tight' (no cross-VLAN) or 'loose' (controlled egress).
        egress: 'blocked' / 'allowed' / 'restricted'.
        dhcp:   Whether to enable Proxmox-side DHCP for in-network clients.
    """

    bridge: str
    cidr: str = ""
    isolation: str = "tight"
    egress: str = "blocked"
    dhcp: bool = True


@dataclass(frozen=True)
class CloneSpec:
    """Inputs to `clone_vm`. All fields are required."""

    source_vmid: int       # VMID of the template on PVE
    new_vmid: int | None   # None => let PVE auto-assign
    node: str              # which PVE node (e.g. "pve")
    name: str              # VM name (must be unique within the node)
    cores: int | None = None
    sockets: int | None = None
    ram_mb: int | None = None
    disk_gb: int | None = None


@dataclass(frozen=True)
class ClonedVM:
    """Result of a successful clone."""

    vmid: int
    node: str
    name: str


@dataclass(frozen=True)
class VmState:
    """Minimal view of a VM used by the runner."""

    vmid: int
    node: str
    name: str
    status: str           # "stopped" | "running" | "paused"
    ip: str | None = None  # primary IP, if known


@dataclass(frozen=True)
class VncTicket:
    """Inputs to ``get_vnc_ticket``.

    PVE's VNC proxy flow is two-step:

      1. POST /nodes/{n}/qemu/{v}/vncproxy  -> { ticket, port }
      2. Open a WebSocket against the same endpoint with
         ``?port=<port>&vncticket=<ticket>``.

    The WS URL also needs ``node`` + ``vmid`` because the API
    proxy re-routes the WS frame to the right noVNC backend.

    Attributes:
        ticket: PVE-issued VNC ticket (hex string).
        port: TCP port the VNC proxy listens on (5900+display
              number; we use PVE's chosen port).
        node: Node that hosts the VMID.
        vmid: VMID the ticket was issued for.
    """

    ticket: str
    port: int
    node: str
    vmid: int


class ProxmoxAdapter(ABC):
    """Operations the runner needs from Proxmox.

    Every method is intentionally small so the mock can be a few dozen
    lines. The real adapter will wrap `proxmoxer.ProxmoxAPI`.
    """

    # --- inventory -------------------------------------------------------

    @abstractmethod
    async def list_nodes(self) -> list[str]:
        """Return names of all PVE nodes."""

    @abstractmethod
    async def find_template(self, name: str) -> int | None:
        """Return the VMID of a template by name, or None."""

    @abstractmethod
    async def allocate_vmid(self) -> int:
        """Reserve the next available VMID."""

    # --- lifecycle -------------------------------------------------------

    @abstractmethod
    async def clone_vm(self, spec: CloneSpec) -> ClonedVM:
        """Clone `source_vmid` on `node` with the given overrides."""

    @abstractmethod
    async def start_vm(self, vmid: int, node: str) -> None:
        """Start a VM; no-op if already running."""

    @abstractmethod
    async def stop_vm(self, vmid: int, node: str, force: bool = False) -> None:
        """Stop a VM; idempotent (no-op if already stopped)."""

    @abstractmethod
    async def destroy_vm(self, vmid: int, node: str) -> None:
        """Delete a VM and free its disk. Idempotent."""

    @abstractmethod
    async def get_vm_state(self, vmid: int, node: str) -> VmState:
        """Return current VM state. Raises KeyError if VM is gone."""

    # --- F3 multi-VM networks ---------------------------------------------
    #
    # The runner iterates spec.networks[] once, creates one bridge per
    # network, and attaches each asset to the bridges that the asset
    # declares in its ``spec.networks[]`` array. The adapter surface is
    # intentionally narrow: create_bridge / remove_bridge for the network,
    # attach_network for the asset side. The mock adapter records every
    # call so tests can assert exact topology.

    @abstractmethod
    async def create_bridge(self, spec: NetworkSpec) -> None:
        """Create (or no-op-on-exists) a Linux bridge on PVE.

        Idempotent: if a bridge with that name already exists, treat
        the call as a no-op. This is important because the runner may
        be retried (cancelled + restarted) and we don't want to fail
        just because the previous teardown didn't fully clean up.
        """

    @abstractmethod
    async def remove_bridge(self, bridge: str) -> None:
        """Delete a bridge created by ``create_bridge``. Idempotent."""

    @abstractmethod
    async def attach_network(self, vmid: int, node: str, bridge: str, nic_id: int) -> None:
        """Add a NIC attached to ``bridge`` to an existing VM.

        The runner calls this once per (asset, network) pair, in
        order, starting from ``nic_id=0`` (next free slot). NIC
        ordering matters: a router that attaches red_vlan first then
        blue_vlan is observable in PVE \`qm config\` output and
        scenarios depend on that ordering to know which interface
        faces which subnet.
        """

    # --- F4 noVNC console -----------------------------------------------
    #
    # PVE exposes the VNC console as a ticket flow: POST
    # /nodes/{n}/qemu/{v}/vncproxy returns a ticket + port, and the
    # browser opens a WebSocket against the same endpoint. We do NOT
    # serve a noVNC HTML page here -- the portal embeds noVNC itself --
    # but we expose the ticket + port so the API can hand the WS URL
    # to the browser via a /drills/{id}/assets/{a}/console endpoint.

    @abstractmethod
    async def get_vnc_ticket(self, vmid: int, node: str) -> VncTicket:
        """Issue a VNC ticket via PVE's /vncproxy endpoint.

        Caller passes the ticket + port to a WebSocket client
        (browser noVNC, or our API-level WS proxy). Tickets
        expire in ~2 hours; the runner reads them once per
        console-open. We don't cache the ticket on the asset
        row because (a) re-issuing on every console-open is
        cheap, and (b) it lets the operator rotate tickets
        without restarting the API.
        """
