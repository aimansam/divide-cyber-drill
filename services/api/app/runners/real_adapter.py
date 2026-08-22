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
- stop_vm(vmid, node, ..) POST /nodes/{n}/qemu/{vmid}/status/stop (+ forceStop=1)
- destroy_vm(vmid, node)  DELETE /nodes/{n}/qemu/{vmid} (+ purge=1&skiplock=1)
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
from typing import Any

from proxmoxer import ProxmoxAPI

from app.core.config import ProxmoxSettings
from app.runners.adapter import (
    CloneSpec,
    ClonedVM,
    ProxmoxAdapter,
    VmState,
)
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError


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
        as `ProxmoxAPIError` so callers have a single error type.
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

        params: dict[str, Any] = {"name": spec.name}
        if spec.new_vmid is not None:
            params["newid"] = spec.new_vmid
        if spec.cores is not None:
            params["cores"] = spec.cores
        if spec.sockets is not None:
            params["sockets"] = spec.sockets
        if spec.ram_mb is not None:
            params["memory"] = spec.ram_mb
        if spec.disk_gb is not None:
            # PVE resize shorthand: scsi0=N resizes the first scsi disk.
            params["disk"] = f"scsi0={spec.disk_gb}G"

        def _do() -> None:
            self._get_client().nodes(node).qemu(spec.source_vmid).clone.post(**params)

        await self._call(_do)
        # If we passed newid, we know it; otherwise allocate via nextid.
        new_vmid = (
            int(spec.new_vmid) if spec.new_vmid is not None else await self.allocate_vmid()
        )
        return ClonedVM(vmid=new_vmid, node=node, name=spec.name)

    async def start_vm(self, vmid: int, node: str) -> None:
        def _do() -> None:
            self._get_client().nodes(node).qemu(vmid).status.start.post()

        await self._call(_do)

    async def stop_vm(self, vmid: int, node: str, force: bool = False) -> None:
        def _do() -> None:
            kwargs: dict[str, Any] = {}
            if force:
                kwargs["forceStop"] = 1
            self._get_client().nodes(node).qemu(vmid).status.stop.post(**kwargs)

        await self._call(_do)

    async def destroy_vm(self, vmid: int, node: str) -> None:
        """Delete VM + purge disk. Idempotent: missing VM is a no-op.

        proxmoxer's DELETE returns the upid of the destroy task; if the VM
        is already gone PVE responds with 404 and we treat that as success
        so callers (runner teardown) can safely re-run.
        """
        def _do() -> None:
            try:
                self._get_client().nodes(node).qemu(vmid).delete(
                    purge=1, skiplock=1
                )
            except Exception as exc:  # noqa: BLE001
                # Be tolerant: PVE returns 404 when VM is gone. proxmoxer
                # raises ResourceException; anything containing "404" or
                # "not found" we treat as idempotent success.
                msg = str(exc).lower()
                if "404" in msg or "not found" in msg or "no such" in msg:
                    return
                raise

        await self._call(_do)

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
