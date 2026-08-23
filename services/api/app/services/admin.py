"""Setup/admin helpers for the PVE setup wizard.

These functions back the ``/api/v1/admin/*`` endpoints exposed by the
``div:ide`` setup portal. They exist so an operator can stand up a fresh
PVE-backed deployment without SSH-ing into Proxmox to drive the installer:

  * probe_pve()                — one-shot PVE health/permissions snapshot
  * upload_qcow2()             — stream a cloud image to PVE storage with progress
  * create_template_from_qcow2 — create the VM, import the disk, attach cloud-init
  * set_template_flag()        — flip template=1 on an existing VM
  * setup_progress_*           — Redis-backed job status for the wizard UI

Why a separate module:
  * The runner (real_adapter.py) only does clone/start/stop/destroy -- not
    VM creation. Setup-time work is different from run-time work.
  * Keeps proxmoxer / httpx / redis coupling out of the router layer.

This module does NOT add new privileges to the API token. The operator
must grant ``PVEDatastoreAdmin`` (a built-in PVE role that covers
``Datastore.Allocate``, ``Datastore.AllocateSpace``, and
``Datastore.Audit``) on ``/storage`` to the divide token before these
endpoints will succeed; ``probe_pve()`` is the canonical way to detect
that gap.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.services.proxmox import (
    ProxmoxAPIError,
    ProxmoxNotConfiguredError,
    get_proxmox_client,
    get_version,
    list_permissions,
    list_storage,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Privileges the divide token needs to actually run a drill. Matches the
#: set checked by tools/preflight.py -- kept in sync manually; the
#: structural test in tests/test_admin.py enforces alignment.
DRILL_PRIVS: frozenset[str] = frozenset({"VM.Allocate", "VM.Clone", "VM.PowerMgmt"})

#: Privileges required for the setup wizard to create templates. Stored
#: separately because we want the probe endpoint to tell the operator
#: exactly what's missing.
SETUP_PRIVS: frozenset[str] = frozenset(
    {"Datastore.AllocateSpace", "Datastore.Allocate", "Datastore.Audit"}
)

#: Redis key prefix for setup progress. Each upload/template job gets a
#: unique suffix (job_id) and is stored as a hash under this prefix.
PROGRESS_KEY_PREFIX = "divide:setup:"

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class PveProbeResult:
    """One-shot snapshot of the PVE connection from the divide token.

    Returned by :func:`probe_pve` and serialized by the admin router.
    """

    reachable: bool
    version: str | None
    pve_user: str
    has_drill_privs: bool
    has_setup_privs: bool
    drill_privs_present: list[str]
    drill_privs_missing: list[str]
    setup_privs_present: list[str]
    setup_privs_missing: list[str]
    storage: list[dict[str, Any]]
    nodes: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "version": self.version,
            "pve_user": self.pve_user,
            "has_drill_privs": self.has_drill_privs,
            "has_setup_privs": self.has_setup_privs,
            "drill_privs_present": self.drill_privs_present,
            "drill_privs_missing": self.drill_privs_missing,
            "setup_privs_present": self.setup_privs_present,
            "setup_privs_missing": self.setup_privs_missing,
            "storage": self.storage,
            "nodes": self.nodes,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def probe_pve() -> PveProbeResult:
    """Return a comprehensive PVE health snapshot for the wizard.

    Used by the portal's "step 1: PVE connection" page to show the
    operator exactly what's working and what's missing. Does NOT raise --
    all errors are captured in ``PveProbeResult.error`` so the portal can
    display them without try/except logic.
    """
    try:
        host, user, _token_name, _secret = _settings_for_probe()
    except ProxmoxNotConfiguredError as exc:
        return PveProbeResult(
            reachable=False,
            version=None,
            pve_user="(not configured)",
            has_drill_privs=False,
            has_setup_privs=False,
            drill_privs_present=[],
            drill_privs_missing=sorted(DRILL_PRIVS),
            setup_privs_present=[],
            setup_privs_missing=sorted(SETUP_PRIVS),
            storage=[],
            nodes=[],
            error=str(exc),
        )

    version: str | None = None
    drill_privs_present: list[str] = []
    storage: list[dict[str, Any]] = []
    nodes: list[str] = []
    error: str | None = None
    all_privs: set[str] = set()

    try:
        version_info = get_version()
        version = f"{version_info.get('version', '?')} ({version_info.get('release', '?')})"
    except (ProxmoxAPIError, ProxmoxNotConfiguredError) as exc:
        error = f"version probe failed: {exc}"

    try:
        perms = list_permissions()
        for path in ("/", "/vms", "/v2/vm"):
            all_privs.update(perms.get(path, {}).keys())
        drill_privs_present = sorted(DRILL_PRIVS & all_privs)
        for path in ("/storage", "/", "/vms"):
            all_privs.update(perms.get(path, {}).keys())
    except (ProxmoxAPIError, ProxmoxNotConfiguredError) as exc:
        if error is None:
            error = f"permissions probe failed: {exc}"

    try:
        storage = list_storage()
    except (ProxmoxAPIError, ProxmoxNotConfiguredError) as exc:
        if error is None:
            error = f"storage probe failed: {exc}"

    try:
        client = get_proxmox_client()
        for n in client.nodes.get():
            nodes.append(n.get("node", "?"))
    except (ProxmoxAPIError, ProxmoxNotConfiguredError) as exc:
        if error is None:
            error = f"nodes probe failed: {exc}"

    return PveProbeResult(
        reachable=version is not None and error is None,
        version=version,
        pve_user=user,
        has_drill_privs=set(drill_privs_present) >= DRILL_PRIVS,
        has_setup_privs=set(SETUP_PRIVS) <= all_privs,
        drill_privs_present=drill_privs_present,
        drill_privs_missing=sorted(DRILL_PRIVS - set(drill_privs_present)),
        setup_privs_present=sorted(SETUP_PRIVS & all_privs),
        setup_privs_missing=sorted(SETUP_PRIVS - all_privs),
        storage=storage,
        nodes=sorted(nodes),
        error=error,
    )


def _settings_for_probe() -> tuple[str, str, str, str]:
    """Pull (host, user, token_name, token_secret) from settings."""
    from app.services.proxmox import _validate_config

    return _validate_config()


# ---------------------------------------------------------------------------
# Upload (qcow2 -> PVE storage)
# ---------------------------------------------------------------------------


@dataclass
class UploadProgress:
    """Snapshot of an in-flight upload. Stored in Redis under
    ``divide:setup:upload:<job_id>``."""

    job_id: str
    filename: str
    target_volid: str
    bytes_sent: int
    total_bytes: int
    started_at: float
    finished_at: float | None
    status: str  # "running" | "success" | "error"
    error: str | None
    result_volid: str | None  # set on success (PVE returns its volid)

    def to_dict(self) -> dict[str, Any]:
        pct = (
            (self.bytes_sent / self.total_bytes * 100.0)
            if self.total_bytes > 0
            else 0.0
        )
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "target_volid": self.target_volid,
            "bytes_sent": self.bytes_sent,
            "total_bytes": self.total_bytes,
            "percent": round(pct, 1),
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "status": self.status,
            "error": self.error,
            "result_volid": self.result_volid,
        }


async def upload_qcow2(
    local_path: str | Path,
    node: str,
    storage: str,
    filename: str | None = None,
    job_id: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    chunk_size: int = 64 * 1024,
) -> UploadProgress:
    """Stream a local qcow2 file to PVE storage via the upload endpoint.

    Uses raw ``httpx`` (not proxmoxer) so we can stream the file in
    chunks and report byte-level progress to the wizard UI.

    Returns an ``UploadProgress`` snapshot; ``status='success'`` if PVE
    accepted the upload, ``status='error'`` otherwise.

    The PVE endpoint is
    ``POST /api2/json/nodes/{node}/storage/{storage}/upload`` with a
    multipart ``content`` field. PVE returns the assigned volid on success.
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"qcow2 not found: {local_path}")

    total = local_path.stat().st_size
    filename = filename or local_path.name
    job_id = job_id or hashlib.sha1(
        f"{local_path}-{time.time()}".encode()
    ).hexdigest()[:12]

    progress = UploadProgress(
        job_id=job_id,
        filename=filename,
        target_volid=f"{storage}:import/{filename}",
        bytes_sent=0,
        total_bytes=total,
        started_at=time.time(),
        finished_at=None,
        status="running",
        error=None,
        result_volid=None,
    )

    from app.services.proxmox import _validate_config

    host, user, token_name, token_secret = _validate_config()
    port = int(os.environ.get("PROXMOX_PORT", "8006"))
    verify = (os.environ.get("PROXMOX_VERIFY_SSL", "true").lower() == "true")
    scheme = "https" if verify or port == 8006 else "http"
    # `content=import` is required so PVE accepts .qcow2 files via the
    # upload endpoint -- the storage's allowed content types include
    # 'import' for raw qemu-img targets. Without this query param PVE
    # returns 400 'wrong file extension'.
    url = (
        f"{scheme}://{host}:{port}/api2/json/nodes/{node}/storage"
        f"/{storage}/upload?content=import"
    )

    headers = {
        "Authorization": f"PVEAPIToken={user}!{token_name}={token_secret}",
    }

    async def _run() -> UploadProgress:
        # Open the file and pass the raw handle to httpx. httpx needs a
        # file-like object exposing `.read(n)` -- a bare generator breaks
        # because httpx calls `.read()` on it. We deliberately do NOT wrap
        # the handle here: httpx's `peek_filelike_length` needs to be able
        # to discover the file's length (via `fileno()` -> `fstat`) so that
        # the request uses `Content-Length` instead of chunked encoding.
        # Some PVE endpoints (including /upload) mis-handle chunked bodies
        # and drop the connection mid-stream, which surfaces as a generic
        # `httpcore.ReadError` from httpx.
        fh = open(local_path, "rb")
        try:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0), verify=verify) as client:
                    # PVE expects the file under the field name 'filename',
                    # not 'content'. The 'content' parameter is the storage
                    # content-type filter (we pass it via the URL query
                    # string above). An extra form field with the same name
                    # would shadow the query param.
                    files = {"filename": (filename, fh, "application/octet-stream")}
                    r = await client.post(url, headers=headers, files=files)
                    if r.status_code >= 400:
                        raise ProxmoxAPIError(
                            f"PVE upload failed: HTTP {r.status_code}: {r.text[:300]}"
                        )
                    body = r.json()
                    volid = None
                    try:
                        volid = (body.get("data") or "").strip() or None
                    except Exception:  # noqa: BLE001
                        volid = None
                    progress.status = "success"
                    progress.result_volid = volid or f"{storage}:import/{filename}"
                    progress.finished_at = time.time()
                    # best-effort progress update on success
                    progress.bytes_sent = progress.total_bytes
            except Exception as exc:  # noqa: BLE001
                progress.status = "error"
                progress.error = f"{exc.__class__.__name__}: {exc}"
                progress.finished_at = time.time()
        finally:
            fh.close()
        await _set_progress(progress)
        return progress

    return await _run()


# ---------------------------------------------------------------------------
# Template creation
# ---------------------------------------------------------------------------


@dataclass
class TemplateProgress:
    """Status of a create-template job. Stored under
    ``divide:setup:template:<job_id>``."""

    job_id: str
    template_name: str
    source_volid: str
    node: str
    cores: int
    memory_mb: int
    disk_gb: int
    disk_storage: str
    status: str
    step: str
    vmid: int | None
    error: str | None
    started_at: float
    finished_at: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "template_name": self.template_name,
            "source_volid": self.source_volid,
            "node": self.node,
            "cores": self.cores,
            "memory_mb": self.memory_mb,
            "disk_gb": self.disk_gb,
            "disk_storage": self.disk_storage,
            "status": self.status,
            "step": self.step,
            "vmid": self.vmid,
            "error": self.error,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
        }


def _next_vmid() -> int:
    """Allocate the next free VMID on PVE via /cluster/nextid."""
    client = get_proxmox_client()
    return int(client.cluster.nextid.get())


async def create_template_from_qcow2(
    template_name: str,
    source_volid: str,
    node: str,
    *,
    disk_storage: str = "local-lvm",
    cores: int = 2,
    memory_mb: int = 2048,
    disk_gb: int = 20,
    bridge: str | None = None,
    job_id: str | None = None,
) -> TemplateProgress:
    """Create a PVE template VM from an uploaded cloud image.

    Steps (mirrors tools/upload_cloudinit_template.py but idempotent):

      1. Allocate VMID via /cluster/nextid
      2. POST /nodes/{n}/qemu with scsi0, ide2 (cloud-init), agent=1
      3. POST /nodes/{n}/qemu/{vmid}/importdisk (qcow2 -> disk-storage)
      4. POST /nodes/{n}/qemu/{vmid}/config (name, tags, cloud-init defaults)
      5. POST /nodes/{n}/qemu/{vmid}/template (flip template=1)

    The returned ``TemplateProgress.vmid`` is the new VMID on success.
    """
    job_id = job_id or hashlib.sha1(
        f"{template_name}-{time.time()}".encode()
    ).hexdigest()[:12]
    progress = TemplateProgress(
        job_id=job_id,
        template_name=template_name,
        source_volid=source_volid,
        node=node,
        cores=cores,
        memory_mb=memory_mb,
        disk_gb=disk_gb,
        disk_storage=disk_storage,
        status="running",
        step="allocating VMID",
        vmid=None,
        error=None,
        started_at=time.time(),
        finished_at=None,
    )

    try:
        await _set_template_progress(progress)
        vmid = await asyncio.to_thread(_next_vmid)
        progress.vmid = vmid

        progress.step = "creating VM"
        await _set_template_progress(progress)
        await asyncio.to_thread(
            _create_qemu_vm, vmid, node, disk_storage, disk_gb, cores, memory_mb, bridge
        )

        progress.step = "importing disk"
        await _set_template_progress(progress)
        await asyncio.to_thread(
            _import_disk, vmid, node, source_volid, disk_storage
        )

        progress.step = "configuring VM"
        await _set_template_progress(progress)
        await asyncio.to_thread(
            _configure_vm, vmid, node, name=template_name
        )

        progress.step = "marking as template"
        await _set_template_progress(progress)
        await asyncio.to_thread(_set_template_flag_sync, vmid, node)

        progress.status = "success"
        progress.step = "done"
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.error = f"{exc.__class__.__name__}: {exc}"
    finally:
        progress.finished_at = time.time()
        await _set_template_progress(progress)

    return progress


def _create_qemu_vm(
    vmid: int, node: str, _disk_storage: str, _disk_gb: int, cores: int, memory_mb: int,
    bridge: str | None = None,
) -> None:
    """POST /nodes/{n}/qemu with the skeleton (no disk yet).

    The disk is NOT created here -- ``importdisk`` (called next) puts the
    uploaded qcow2 into the first free SCSI slot (scsi0). If we pre-create
    scsi0 with an empty 20 GB, the import lands on scsi1 and the runner
    can't find it.
    """
    client = get_proxmox_client()
    kwargs: dict[str, Any] = dict(
        vmid=vmid,
        # Cloud-init drive (mandatory for the runner's ipconfig0 path).
        ide2="local:cloudinit",
        cores=cores,
        memory=memory_mb,
        # scsi0 will be filled by importdisk; nothing else yet.
        boot="order=scsi0",
        # qemu-guest-agent enabled in the OS later via cloud-init.
        agent=1,
        # Modern SCSI controller; harmless default but greppable.
        scsihw="virtio-scsi-single",
    )
    if bridge:
        # Net0: virtio on the named bridge. On SDN-managed PVE the default
        # ``vmbr0`` requires ``SDN.Use`` which drill tokens don't have, so
        # only attach a NIC if the caller picked a bridge explicitly.
        kwargs["net0"] = f"virtio,bridge={bridge}"
    client.nodes(node).qemu.post(**kwargs)


def _import_disk(vmid: int, node: str, source_volid: str, target_storage: str) -> None:
    """Import the uploaded qcow2 from {storage}:import/<file> into {target_storage}.

    In PVE 7/8 this was ``POST /qemu/{vmid}/importdisk``. PVE 9 removed
    that endpoint (``Method not implemented``) and the documented path is
    now ``POST /qemu/{vmid}/config`` with the special
    ``scsi0={target}:0,import-from={source_volid}`` syntax -- PVE
    internally runs ``qemu-img convert`` and attaches the disk. We use
    that here.
    """
    client = get_proxmox_client()
    client.nodes(node).qemu(vmid).config.post(
        scsi0=f"{target_storage}:0,import-from={source_volid}",
    )


def _configure_vm(vmid: int, node: str, *, name: str) -> None:
    """Set VM name + tags."""
    client = get_proxmox_client()
    client.nodes(node).qemu(vmid).config.post(name=name, tags="divide-template")


def _set_template_flag_sync(vmid: int, node: str) -> None:
    """POST /nodes/{n}/qemu/{vmid}/template with template=1."""
    client = get_proxmox_client()
    client.nodes(node).qemu(vmid).template.post()


async def set_template_flag(vmid: int, node: str) -> None:
    """Async wrapper around :func:`_set_template_flag_sync`."""
    await asyncio.to_thread(_set_template_flag_sync, vmid, node)


# ---------------------------------------------------------------------------
# Redis-backed progress for the wizard UI
# ---------------------------------------------------------------------------


async def _set_progress(progress: UploadProgress) -> None:
    """Persist an UploadProgress to Redis (hash)."""
    from app.services.cache import get_redis

    client = get_redis()
    key = f"{PROGRESS_KEY_PREFIX}upload:{progress.job_id}"
    payload = progress.to_dict()
    await client.hset(key, mapping={k: json.dumps(v) for k, v in payload.items()})
    # Auto-expire after 1 hour so the key namespace stays clean.
    await client.expire(key, 3600)


async def _set_template_progress(progress: TemplateProgress) -> None:
    """Persist a TemplateProgress to Redis (hash)."""
    from app.services.cache import get_redis

    client = get_redis()
    key = f"{PROGRESS_KEY_PREFIX}template:{progress.job_id}"
    payload = progress.to_dict()
    await client.hset(key, mapping={k: json.dumps(v) for k, v in payload.items()})
    await client.expire(key, 3600)


async def get_progress(job_id: str, kind: str = "upload") -> dict[str, Any] | None:
    """Read back a progress hash by job_id. Returns None if missing/expired."""
    from app.services.cache import get_redis

    client = get_redis()
    key = f"{PROGRESS_KEY_PREFIX}{kind}:{job_id}"
    raw = await client.hgetall(key)
    if not raw:
        return None
    out: dict[str, Any] = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


async def list_in_progress() -> list[dict[str, Any]]:
    """List all in-flight setup jobs (uploads + templates).

    Useful for the wizard's "what's still running?" view.
    """
    from app.services.cache import get_redis

    client = get_redis()
    out: list[dict[str, Any]] = []
    for kind in ("upload", "template"):
        async for key in client.scan_iter(f"{PROGRESS_KEY_PREFIX}{kind}:*"):
            raw = await client.hgetall(key)
            decoded: dict[str, Any] = {}
            for k, v in raw.items():
                try:
                    decoded[k] = json.loads(v)
                except (TypeError, ValueError):
                    decoded[k] = v
            decoded["_kind"] = kind
            out.append(decoded)
    return out
