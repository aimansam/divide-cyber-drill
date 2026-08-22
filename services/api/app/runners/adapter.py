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
