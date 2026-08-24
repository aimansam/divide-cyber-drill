"""In-memory fake of ProxmoxAdapter.

Used by tests + tools/run_smoke.py. Tracks:
  * "Inventory" of nodes + templates + VMIDs (small finite set)
  * The full call history (cloned / started / stopped / destroyed)
    for assertions in tests

Behaviour
---------
- Templates live in a registry you seed up-front; find_template looks them up.
- allocate_vmid starts at 9000 and never reuses.
- clone_vm returns a deterministic "10.0.x.y" IP for each VMID so tests
  can assert exact values.
- All methods are async (mirror the real adapter's surface) but do no I/O.
- Calling destroy_vm on a missing VM is a no-op (idempotent contract).
"""
from __future__ import annotations

from dataclasses import dataclass

from .adapter import ClonedVM, CloneSpec, NetworkSpec, ProxmoxAdapter, VmState


@dataclass
class _Vm:
    vmid: int
    node: str
    name: str
    status: str = "stopped"
    ip: str | None = None
    is_template: bool = False
    # Ordered list of (nic_id, bridge_name) attached to this VM.
    # F3 (multi-VM scenarios) populates this; the runner asserts
    # ordering and count to verify the topology.
    nics: list[tuple[int, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.nics is None:
            self.nics = []


class MockProxmoxAdapter(ProxmoxAdapter):
    """Deterministic in-memory ProxmoxAdapter for tests + smoke."""

    def __init__(
        self,
        nodes: list[str] | None = None,
        templates: dict[str, int] | None = None,
        next_vmid: int = 9000,
        ip_template: str = "10.10.99.{vmid_offset}",
    ) -> None:
        self._nodes: list[str] = list(nodes or ["pve"])
        self._templates: dict[str, int] = dict(templates or {})
        self._next_vmid: int = next_vmid
        self._ip_template = ip_template
        self._vms: dict[int, _Vm] = {}
        # Set of bridge names that have been created (F3). Idempotent on
        # repeated create_bridge calls.
        self._bridges: set[str] = set()
        # Seed templates as VM entries so get_vm_state works on them.
        for name, vmid in self._templates.items():
            self._vms[vmid] = _Vm(
                vmid=vmid, node=self._nodes[0], name=name, is_template=True
            )
        # Public, read-only call history (assertion target).
        self.cloned: list[CloneSpec] = []
        self.cloned_results: list[ClonedVM] = []
        self.started: list[tuple[int, str]] = []
        self.stopped: list[tuple[int, str, bool]] = []
        self.destroyed: list[tuple[int, str]] = []
        # F3 multi-VM scenarios history:
        self.bridges_created: list[NetworkSpec] = []
        self.bridges_removed: list[str] = []
        self.nic_attached: list[tuple[int, str, int]] = []

    # --- inventory -------------------------------------------------------

    async def list_nodes(self) -> list[str]:
        return list(self._nodes)

    async def find_template(self, name: str) -> int | None:
        return self._templates.get(name)

    async def allocate_vmid(self) -> int:
        vmid = self._next_vmid
        self._next_vmid += 1
        return vmid

    # --- lifecycle -------------------------------------------------------

    async def clone_vm(self, spec: CloneSpec) -> ClonedVM:
        self.cloned.append(spec)
        if spec.source_vmid not in self._vms:
            raise KeyError(f"template vmid {spec.source_vmid} not found")
        new_vmid = spec.new_vmid if spec.new_vmid is not None else await self.allocate_vmid()
        ip = self._ip_template.format(vmid_offset=new_vmid - 8999)
        vm = _Vm(
            vmid=new_vmid,
            node=spec.node,
            name=spec.name,
            status="stopped",
            ip=ip,
        )
        self._vms[new_vmid] = vm
        result = ClonedVM(vmid=new_vmid, node=spec.node, name=spec.name)
        self.cloned_results.append(result)
        return result

    async def start_vm(self, vmid: int, node: str) -> None:
        self.started.append((vmid, node))
        vm = self._require_vm(vmid, node)
        vm.status = "running"

    async def stop_vm(self, vmid: int, node: str, force: bool = False) -> None:
        self.stopped.append((vmid, node, force))
        if vmid in self._vms:
            self._vms[vmid].status = "stopped"

    async def destroy_vm(self, vmid: int, node: str) -> None:
        self.destroyed.append((vmid, node))
        self._vms.pop(vmid, None)

    # --- F3 multi-VM networks -----------------------------------------

    async def create_bridge(self, spec: NetworkSpec) -> None:
        """Idempotent: re-creating an existing bridge is a no-op."""
        self.bridges_created.append(spec)
        self._bridges.add(spec.bridge)

    async def remove_bridge(self, bridge: str) -> None:
        """Idempotent: removing a non-existent bridge is a no-op."""
        self.bridges_removed.append(bridge)
        self._bridges.discard(bridge)

    async def attach_network(
        self, vmid: int, node: str, bridge: str, nic_id: int
    ) -> None:
        vm = self._require_vm(vmid, node)
        self.nic_attached.append((vmid, bridge, nic_id))
        vm.nics.append((nic_id, bridge))

    async def get_vm_state(self, vmid: int, node: str) -> VmState:
        vm = self._require_vm(vmid, node)
        return VmState(
            vmid=vm.vmid,
            node=vm.node,
            name=vm.name,
            status=vm.status,
            ip=vm.ip,
        )

    # --- helpers for tests ----------------------------------------------

    def seed_template(self, name: str, vmid: int | None = None, node: str = "pve") -> int:
        """Add a template to the registry. Returns the VMID used.

        If `vmid` is None, a VMID is allocated via `allocate_vmid()`.
        Either way, the counter advances so clones never collide with
        template VMIDs.
        """
        if vmid is None:
            vmid = self._next_vmid
            self._next_vmid += 1
        elif vmid >= self._next_vmid:
            self._next_vmid = vmid + 1
        self._templates[name] = vmid
        self._vms[vmid] = _Vm(
            vmid=vmid, node=node, name=name, is_template=True
        )
        return vmid

    def _require_vm(self, vmid: int, node: str) -> _Vm:
        if vmid not in self._vms:
            raise KeyError(f"vmid {vmid} not found on node {node}")
        return self._vms[vmid]
