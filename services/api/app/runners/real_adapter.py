"""ProxmoxAdapter implementation backed by `proxmoxer`.

Why this exists
---------------
The runner owns the Proxmox lifecycle (clone/start/stop/destroy). For tests
and dev, a deterministic in-memory adapter is enough (see mock_adapter.py).
This module is the **production** implementation: it talks to a real PVE
host via `proxmoxer.ProxmoxAPI`.

Mapping (ABC -> PVE REST)
-------------------------
- list_nodes()            GET /nodes
- find_template(name)     GET /cluster/resources?type=vm (filter template=1 && name==)
- allocate_vmid()         POST /cluster/nextid
- clone_vm(spec)          POST /nodes/{n}/qemu/{vmid}/clone
- start_vm(vmid, node)    POST /nodes/{n}/qemu/{vmid}/status/start
- stop_vm(vmid, node, ..) POST /nodes/{n}/qemu/{vmid}/status/stop (+ timeout=N)
- destroy_vm(vmid, node)  DELETE /nodes/{n}/qemu/{vmid} (+ purge=1)
- get_vm_state(vmid, n)   GET /nodes/{n}/qemu/{vmid}/status/current

Concurrency model
-----------------
`proxmoxer.ProxmoxAPI` is synchronous and uses `requests` under the hood. We
bridge it to our async `ProxmoxAdapter` surface via `asyncio.to_thread`, so
the event loop is never blocked on network I/O.

Errors
------
All proxmoxer exceptions are wrapped as `ProxmoxAPIError` (reused from
`app.services.proxmox`). Missing/incomplete config raises
`ProxmoxNotConfiguredError`. Per-call timeouts also surface as
`ProxmoxAPIError` with a clear message — never as an asyncio.TimeoutError,
which the runner doesn't know how to handle.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from proxmoxer import ProxmoxAPI

from app.core.config import ProxmoxSettings
from app.runners.adapter import (
    CloneSpec,
    ClonedVM,
    NetworkSpec,
    ProxmoxAdapter,
    VmState,
)
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError

log = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_S = 30.0


class RealProxmoxAdapter(ProxmoxAdapter):
    """Adapter that talks to a real Proxmox VE host via proxmoxer.

    Construct either via `RealProxmoxAdapter.from_settings(p)` (preferred,
    pulls all auth + network config from the app's `ProxmoxSettings`) or
    directly with `(host, port, user, token_id, token_secret, verify_ssl)`
    — useful for tests and one-off scripts.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        token_id: str,
        token_secret: str,
        verify_ssl: bool = True,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if not host:
            raise ProxmoxNotConfiguredError("Proxmox host is empty")
        if not token_id or not token_secret:
            raise ProxmoxNotConfiguredError(
                "Proxmox token_id and token_secret are required"
            )
        self._host = host.split("://", 1)[-1].rstrip("/") if "://" in host else host
        self._port = int(port)
        self._user = user
        # PROXMOX_TOKEN_ID is the full "user!tokenname" string. proxmoxer
        # wants (user, token_name) separately:
        token_full = token_id.strip()
        self._token_name = token_full.split("!", 1)[1] if "!" in token_full else token_full
        self._token_secret = token_secret
        self._verify_ssl = verify_ssl
        self._timeout_s = float(timeout_s)
        self._client: ProxmoxAPI | None = None
        # Default node for F3 multi-VM scenarios. The runner currently
        # operates on a single node per drill (see runner.py), so we
        # stash that here for create_bridge to use. Tests pass
        # ``node`` explicitly per-call elsewhere, but create_bridge
        # doesn't take a node arg, so we use this for the default.
        self._node: str | None = None

    # --- construction ----------------------------------------------------

    @classmethod
    def from_settings(cls, p: ProxmoxSettings) -> RealProxmoxAdapter:
        """Build from `app.core.config.ProxmoxSettings`.

        Raises ProxmoxNotConfiguredError if host or token are missing —
        callers (the factory in `runner.py`) should catch and fall back to
        the mock if desired.
        """
        host = (p.host or "").strip()
        if not host:
            raise ProxmoxNotConfiguredError("PROXMOX_HOST is not set")
        token_id = (p.token_id or "").strip()
        token_secret_raw = p.token_secret
        token_secret = (
            token_secret_raw.get_secret_value() if token_secret_raw is not None else None
        )
        if not token_id or not token_secret:
            raise ProxmoxNotConfiguredError(
                "PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET must be set"
            )
        return cls(
            host=host,
            port=int(p.port),
            user=p.user,
            token_id=token_id,
            token_secret=token_secret,
            verify_ssl=bool(p.verify_ssl),
        )

    # --- internal client + call helpers ---------------------------------

    def _get_client(self) -> ProxmoxAPI:
        if self._client is None:
            self._client = ProxmoxAPI(
                host=self._host,
                port=self._port,
                user=self._user,
                token_name=self._token_name,
                token_value=self._token_secret,
                verify_ssl=self._verify_ssl,
                backend="https",
            )
        return self._client

    async def _call(self, fn, *args: Any, **kwargs: Any) -> Any:
        """Run a sync proxmoxer call in a worker thread with a timeout.

        Any exception raised by `fn` (proxmoxer or anything else) is wrapped
        as `ProxmoxAPIError` so callers have a single error type. 403s get a
        short ACL hint appended so the operator knows to grant PVEVMAdmin.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args, **kwargs),
                timeout=self._timeout_s,
            )
        except ProxmoxNotConfiguredError:
            raise
        except asyncio.TimeoutError as exc:
            raise ProxmoxAPIError(
                f"proxmoxer call timed out after {self._timeout_s}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "403" in msg or "Permission check failed" in msg:
                raise ProxmoxAPIError(
                    f"{type(exc).__name__}: {exc} — token needs PVEVMAdmin "
                    f"(or PVEAdmin) on /v2/vm; see docs/PROXMOX-SETUP.md §6"
                ) from exc
            raise ProxmoxAPIError(f"{type(exc).__name__}: {exc}") from exc

    # --- inventory -------------------------------------------------------

    async def list_nodes(self) -> list[str]:
        def _do() -> list[str]:
            return [n["node"] for n in self._get_client().nodes.get()]

        return await self._call(_do)

    async def find_template(self, name: str) -> int | None:
        def _do() -> int | None:
            resources = self._get_client().cluster.resources.get(type="vm")
            for r in resources:
                # PVE returns `template=1` for templates, 0/None for regular VMs.
                if r.get("template") and r.get("name") == name:
                    return int(r["vmid"])
            return None

        return await self._call(_do)

    async def allocate_vmid(self) -> int:
        def _do() -> int:
            # PVE 8+/9: `/cluster/nextid` is a GET, not POST. POST returns
            # 501 Not Implemented on PVE 9.1.7. Older docs and the proxmoxer
            # default assume POST, so we explicitly use GET for forward
            # compatibility.
            return int(self._get_client().cluster.nextid.get())

        return await self._call(_do)

    # --- lifecycle -------------------------------------------------------

    async def clone_vm(self, spec: CloneSpec) -> ClonedVM:
        if spec.source_vmid is None:
            raise ProxmoxAPIError("clone_vm requires source_vmid")
        node = spec.node
        if not node:
            raise ProxmoxAPIError("clone_vm requires a target node")

        # PVE 9 split clone + post-clone config:
        #   * ``clone.post`` only accepts clone-time params (name, newid).
        #   * Per-resource overrides (cores, sockets, memory) go via
        #     ``config.post`` on the new VMID.
        #   * Disk resize goes via ``PUT /qemu/{vmid}/resize`` with
        #     ``disk=scsi0&size=+XG`` -- ``config.post`` rejects ``disk``
        #     on PVE 9 with ``property is not defined in schema``.
        
        # Allocate VMID BEFORE cloning to ensure we know the exact VMID
        new_vmid = int(spec.new_vmid) if spec.new_vmid is not None else await self.allocate_vmid()
        
        clone_params: dict[str, Any] = {"name": spec.name, "newid": new_vmid}

        def _do() -> None:
            self._get_client().nodes(node).qemu(spec.source_vmid).clone.post(**clone_params)

        await self._call(_do)

        config_overrides: dict[str, Any] = {}
        if spec.cores is not None:
            config_overrides["cores"] = spec.cores
        if spec.sockets is not None:
            config_overrides["sockets"] = spec.sockets
        if spec.ram_mb is not None:
            config_overrides["memory"] = spec.ram_mb

        if config_overrides:
            def _config() -> None:
                self._get_client().nodes(node).qemu(new_vmid).config.post(**config_overrides)

            await self._call(_config)

        if spec.disk_gb is not None:
            def _resize() -> None:
                self._get_client().nodes(node).qemu(new_vmid).resize.put(
                    disk="scsi0",
                    size=f"+{spec.disk_gb}G",
                )

            await self._call(_resize)

        # Q27: Fix cloud-init drive storage migration.
        # PVE clones copy disk references as-is. If the template has
        # cloud-init on `local` storage (which doesn't support `images`
        # content type), the cloned VM won't start. Move cloud-init
        # drives from `local` to `local-lvm` after cloning.
        await self._fix_cloud_init_storage(new_vmid, node)

        return ClonedVM(vmid=new_vmid, node=node, name=spec.name)

    async def start_vm(self, vmid: int, node: str) -> None:
        def _do() -> None:
            self._get_client().nodes(node).qemu(vmid).status.start.post()

        await self._call(_do)

        # Q27: Verify VM actually started. PVE may accept the start
        # command but the VM could fail to boot (e.g., storage issues).
        # Wait briefly and check status.
        import time
        time.sleep(2)
        
        def _check() -> dict:
            return self._get_client().nodes(node).qemu(vmid).status.current.get()
        
        status = await self._call(_check)
        if status.get("status") != "running":
            raise ProxmoxAPIError(
                f"VM {vmid} failed to start: status={status.get('status')}, "
                f"qmpstatus={status.get('qmpstatus')}"
            )

    async def stop_vm(self, vmid: int, node: str, force: bool = False) -> None:
        """Stop a VM.

        PVE 9 dropped the legacy ``forceStop=1`` parameter that older
        proxmoxer versions emitted -- the schema now rejects it with
        ``property is not defined in schema``. We pass ``timeout=N``
        which IS supported on PVE 9 (positive int = max wait seconds;
        0 = skip the ACPI shutdown and power off immediately, which
        is the documented "force" behaviour).

        ``force=True`` from the caller maps to ``timeout=0`` so we
        skip the ACPI shutdown. ``force=False`` uses ``timeout=60``
        to give the guest a chance to flush its disks.
        """
        timeout = 0 if force else 60

        def _do() -> None:
            self._get_client().nodes(node).qemu(vmid).status.stop.post(
                timeout=timeout
            )

        await self._call(_do)

        # Q27: Wait for VM to actually stop before returning.
        # PVE stop command is async - it returns immediately but
        # the VM may still be shutting down. Without this wait,
        # destroy_vm can fail with "VM is running" error.
        import time
        for _ in range(30):  # Wait up to 30 seconds
            time.sleep(1)
            def _check() -> dict:
                return self._get_client().nodes(node).qemu(vmid).status.current.get()
            status = await self._call(_check)
            if status.get("status") == "stopped":
                break
        else:
            log.warning("stop_vm timeout waiting for vmid=%s to stop", vmid)

    async def destroy_vm(self, vmid: int, node: str) -> None:
        """Delete VM + purge disk. Idempotent: missing VM is a no-op.

        proxmoxer's DELETE returns the upid of the destroy task; if the VM
        is already gone PVE responds with 404 and we treat that as success
        so callers (runner teardown) can safely re-run.
        """
        def _do() -> None:
            try:
                # Q17: drop ``skiplock=1`` -- PVE 9 reserves it for
                # ``root@pam`` and rejects non-superuser tokens with
                # "Only root may use this option". ``purge=1`` alone
                # destroys the VM + its disks, which is what the
                # runner always wants on cleanup. Operators running
                # the DivideDrill role don't race against PVE's
                # internal VM locks; they own the VM namespace.
                self._get_client().nodes(node).qemu(vmid).delete(
                    purge=1
                )
            except Exception as exc:  # noqa: BLE001
                # Be tolerant: PVE returns 404 when the VM is gone
                # in older versions, but **PVE 9 returns HTTP 500**
                # with body ``Configuration file 'nodes/pve/qemu-server/
                # {vmid}.conf' does not exist`` -- proxmoxer surfaces
                # this as ``ResourceException`` whose message contains
                # "does not exist". Treat both as idempotent success
                # so the runner can re-enter destroy_vm safely.
                msg = str(exc).lower()
                if (
                    "404" in msg
                    or "not found" in msg
                    or "no such" in msg
                    or "does not exist" in msg
                ):
                    return
                raise

        await self._call(_do)

    async def _fix_cloud_init_storage(self, vmid: int, node: str) -> None:
        """Q27: Remove cloud-init drives from cloned VMs.
        
        PVE clones copy disk references as-is. If the template has cloud-init
        on `local` storage (which doesn't support `images` content type), the
        cloned VM won't start because the cloud-init disk image doesn't exist
        at the referenced location.
        
        Solution: Simply remove the cloud-init drive reference from the VM
        config. The cloned VMs are already configured from the template and
        don't need cloud-init to boot.
        
        Cloud-init drives are typically on ide2 (CD-ROM) with naming pattern:
        local:VMID/vm-VMID-cloudinit.qcow2
        
        Also updates boot order to ensure VM boots from hard disk (scsi0)
        instead of trying to boot from removed CD-ROM.
        """
        def _get_config() -> dict:
            return self._get_client().nodes(node).qemu(vmid).config.get()
        
        config = await self._call(_get_config)
        
        # Check for cloud-init drives on local storage
        drives_to_remove = []
        for key, value in config.items():
            if key.startswith("ide") and isinstance(value, str):
                # Check if it's a cloud-init drive on local storage
                if "local:" in value and "cloudinit" in value.lower():
                    drives_to_remove.append(key)
        
        if not drives_to_remove:
            return
        
        log.info(
            "pve_runner.removing_cloud_init_drives vmid=%s drives=%s",
            vmid,
            drives_to_remove,
        )
        
        # Delete cloud-init drive references and set boot order to scsi0
        def _delete_drives_and_set_boot() -> None:
            delete_list = ",".join(drives_to_remove)
            self._get_client().nodes(node).qemu(vmid).config.post(
                **{
                    "delete": delete_list,
                    "boot": "order=scsi0"  # Boot from first SCSI disk
                }
            )
        
        await self._call(_delete_drives_and_set_boot)
        
        log.info(
            "pve_runner.cloud_init_removed vmid=%s drives=%s boot=scsi0",
            vmid,
            drives_to_remove,
        )

    async def get_vm_state(self, vmid: int, node: str) -> VmState:
        """Return current state. PVE returns 'running'|'stopped'|'paused'|...

        IP is taken from the QEMU guest-agent interface (`ipconfig0`) when
        available; otherwise the legacy `ip` field on the status payload.
        Both are best-effort — many drill VMs won't have guest-agent
        installed at clone time, in which case `ip` is None.
        """
        def _do() -> dict:
            return self._get_client().nodes(node).qemu(vmid).status.current.get()

        current = await self._call(_do)

        ip: str | None = None
        # `ip` field is sometimes populated by the agent; otherwise try config.
        if current.get("ip"):
            ip = current["ip"]
        else:
            try:
                cfg = self._get_client().nodes(node).qemu(vmid).config.get()
                ipconfig0 = cfg.get("ipconfig0") or ""
                # Format: "ip=dhcp" or "ip=10.0.0.5/24,gw=10.0.0.1"
                for part in ipconfig0.split(","):
                    kv = part.split("=", 1)
                    if len(kv) == 2 and kv[0] == "ip" and kv[1] not in ("", "dhcp"):
                        ip = kv[1].split("/", 1)[0]
                        break
            except Exception:  # noqa: BLE001
                ip = None

        return VmState(
            vmid=int(current.get("vmid", vmid)),
            node=node,
            name=current.get("name") or f"vmid-{vmid}",
            status=current.get("status", "unknown"),
            ip=ip,
        )

    # --- F3 multi-VM networks -----------------------------------------


    async def get_sdn_bridges(self, zone: str = "divide") -> list[str]:
        """Query SDN VNets in the specified zone and return bridge names.

        This allows the runner to use bridges that are already configured
        in the SDN zone instead of hardcoding bridge names.
        """
        def _do() -> list[str]:
            client = self._get_client()
            vnets = client.cluster.sdn.vnets.get()
            return [v["vnet"] for v in vnets if v.get("zone") == zone]

        return await self._call(_do)

    async def create_sdn_vnet(self, bridge: str, zone: str = "divide") -> None:
        """Create an SDN VNet in the specified zone.

        This ensures the bridge exists in the SDN zone before the runner
        tries to use it. Idempotent: if the VNet already exists, this is
        a no-op.
        """
        def _do() -> None:
            client = self._get_client()
            # Check if VNet already exists
            vnets = client.cluster.sdn.vnets.get()
            existing = [v["vnet"] for v in vnets if v.get("zone") == zone]
            if bridge in existing:
                return  # Already exists, no-op
            
            # Create the VNet
            client.cluster.sdn.vnets.post(
                vnet=bridge,
                zone=zone,
            )
            log.info("pve_runner.sdn_vnet_created bridge=%s zone=%s", bridge, zone)

        await self._call(_do)


    async def create_bridge(self, spec: NetworkSpec) -> None:
        """Create a Linux bridge on every node in the cluster.

        PVE bridges (vmbrN) are per-node, but for the cyber range we
        consistently use a single node for the whole drill so we only
        need to create it on that node. Bridges are managed via PVE's
        Software-Defined Networking stack (see
        ``docs/PROXMOX-SETUP.md §4``): the wizard's Step 0 creates
        the ``divide`` zone + one VNet per declared network via
        ``POST /cluster/sdn/{zones,vnets}``.

        The runner no longer creates bridges itself -- it asserts the
        bridge already exists on the target node (calls
        ``/nodes/{node}/network`` and looks for ``iface == <bridge>``).
        If not found, raises ``ProxmoxAPIError`` with a wizard
        action path, so operators see the missing-bridge reason in
        the run report and can re-run Step 0 of the wizard to fix it.

        The error message no longer references ``/etc/network/interfaces``
        or ``ifreload`` -- those were the SSH-era remediation steps
        and would mislead the operator today.
        """
        def _do() -> None:
            client = self._get_client()
            node_name = self._node or "pve"
            networks = client.nodes(node_name).network.get()
            existing = {n["iface"] for n in networks}
            if spec.bridge not in existing:
                raise ProxmoxAPIError(
                    f"bridge {spec.bridge!r} not configured on PVE node "
                    f"{node_name!r} -- create it via the wizard's Step 0 "
                    f"(POST /api/v1/admin/pve-setup-bridges) or via "
                    f"`pvesh create /cluster/sdn/vnets -vnet {spec.bridge} "
                    f"-zone divide` (see docs/PROXMOX-SETUP.md §4)"
                )

        await self._call(_do)

    async def remove_bridge(self, bridge: str) -> None:
        """Best-effort cleanup of an SDN-created VNet on PVE.

        Since F-pve-bridge-wizard (SDN variant), bridges are managed
        as SDN Vnets in the ``divide`` zone. The runner can delete
        them via ``DELETE /cluster/sdn/vnets/{bridge}`` -- no
        host-shell access required. We do this so that a failed
        drill doesn't leave orphan Vnets accumulating on the cluster.

        Older docstrings said the runner never deletes bridges. That
        was true when bridges were created via ``/etc/network/interfaces``
        (which the runner can't edit). With SDN, deletion is just
        one HTTP call, and leaving the bridge behind leaks cluster
        state. Best-effort: if the PVE call fails (e.g. permissions,
        transient network), we log and move on -- the operator can
        run ``pvesh delete /cluster/sdn/zones/divide`` to wipe the
        whole zone if needed.
        """
        def _do() -> None:
            client = self._get_client()
            try:
                client.cluster.sdn.vnets(bridge).delete()
            except Exception as exc:  # noqa: BLE001
                # Logged here -- the calling code wraps _call() with
                # its own error handling and we don't want to mask
                # a genuine runner failure by raising on cleanup.
                log.warning(
                    "pve_runner.remove_bridge.failed",
                    bridge=bridge,
                    error=str(exc),
                )

        try:
            await self._call(_do)
        except Exception:  # noqa: BLE001
            # Defensive: an SDN-delete that explodes should never
            # break an otherwise-successful drill's teardown.
            pass

    async def attach_network(
        self, vmid: int, node: str, bridge: str, nic_id: int
    ) -> None:
        """Add a NIC attached to ``bridge`` to an existing VM.

        Maps to ``POST /nodes/{n}/qemu/{vmid}/config`` with a
        ``netN`` property of ``model=virtio,bridge=vmbrN,...``. PVE's
        ``nic_id`` 0 is ``net0``. We don't overwrite an existing
        ``netN`` entry — the runner allocates NICs starting at 0
        sequentially so collisions never happen for a freshly cloned
        VM.
        """
        net_name = f"net{nic_id}"

        def _do() -> None:
            client = self._get_client()
            cfg = client.nodes(node).qemu(vmid).config.get()
            if net_name in cfg:
                # Already attached; skip. Idempotent on retries.
                return
            client.nodes(node).qemu(vmid).config.post(
                **{net_name: f"virtio,bridge={bridge}"}
            )

        await self._call(_do)
