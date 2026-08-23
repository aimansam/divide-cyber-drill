"""Admin/setup endpoints for the PVE setup wizard.

Exposed at ``/api/v1/admin/*`` (no auth required for now -- this is a
LAN-only tool for the initial setup). Routes:

  * ``GET  /probe``                         — one-shot PVE snapshot
  * ``GET  /storage``                       — list storage pools
  * ``POST /upload-qcow2``                  — upload a cloud image (multipart)
  * ``POST /create-template``               — turn an uploaded qcow2 into a template
  * ``POST /set-template/{vmid}``           — flip template=1 on existing VM
  * ``GET  /progress/{kind}/{job_id}``      — poll a job's status
  * ``GET  /progress``                      — list in-flight jobs
  * ``GET  /drill-template-status``         — does the canonical template exist?
  * ``POST /start-first-drill``             — convenience: run first-live-drill

Security note: this whole module assumes a trusted LAN. Once L2 lands
(token middleware), these routes will be gated behind an admin role.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.services import admin as admin_svc
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError, list_storage

router = APIRouter()


class ProbeResponse(BaseModel):
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


class CreateTemplateRequest(BaseModel):
    template_name: str
    source_volid: str
    node: str
    disk_storage: str = "local-lvm"
    cores: int = 2
    memory_mb: int = 2048
    disk_gb: int = 20
    # Optional bridge for net0. If unset, ``net0`` is omitted from the
    # VM config -- this lets the operator wire the network after creation
    # (or use the template with the runner's own bridge discovery). On
    # PVE hosts with SDN-managed bridges the default ``vmbr0`` requires
    # ``SDN.Use`` which drill tokens don't have.
    bridge: str | None = None
    job_id: str | None = None


class SetTemplateRequest(BaseModel):
    node: str


class StartFirstDrillRequest(BaseModel):
    timeout_s: int = 300


@router.get(
    "/probe",
    response_model=ProbeResponse,
    summary="One-shot PVE health + permissions snapshot for the wizard",
)
async def probe() -> ProbeResponse:
    """Probe PVE connectivity, version, perms, storage, nodes."""
    result = admin_svc.probe_pve()
    return ProbeResponse(**result.to_dict())


@router.get("/storage", summary="List PVE storage pools (for the wizard UI)")
async def storage_pools() -> dict[str, Any]:
    """Return list of storage pools for the upload dropdown."""
    try:
        items = list_storage()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE unreachable: {exc}",
        ) from exc
    return {"items": items, "total": len(items)}


UPLOAD_TMP_DIR = Path(
    os.environ.get("DIVIDE_UPLOAD_TMP_DIR", "/tmp/divide-uploads")
)


@router.post(
    "/upload-qcow2",
    summary="Upload a cloud image (.qcow2) to PVE storage",
)
async def upload_qcow2(
    file: UploadFile = File(..., description="The .qcow2 file to upload"),  # noqa: B008
    node: str = Form(..., description="PVE node name (e.g. 'pve')"),  # noqa: B008
    storage: str = Form(..., description="Target storage (e.g. 'local')"),  # noqa: B008
    filename: str | None = Form(  # noqa: B008
        default=None,
        description="Override the filename PVE stores under. Defaults to the upload's name.",
    ),
) -> dict[str, Any]:
    """Stream the uploaded qcow2 to PVE, returning a job_id for progress polling."""
    # mkdir is a one-shot at the start of an upload; do it via os to
    # avoid the async-pathlib lint (this isn't on the hot path).
    os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)
    target = UPLOAD_TMP_DIR / (filename or file.filename or "upload.qcow2")

    written = 0
    with target.open("wb") as fh:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            written += len(chunk)

    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty upload",
        )

    try:
        progress = await admin_svc.upload_qcow2(
            local_path=target,
            node=node,
            storage=storage,
            filename=filename or file.filename,
        )
    finally:
        target.unlink(missing_ok=True)

    if progress.status == "error":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=progress.error or "PVE upload failed",
        )

    return progress.to_dict()


@router.post(
    "/create-template",
    summary="Create a PVE template VM from an uploaded qcow2",
)
async def create_template(body: CreateTemplateRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Kick off template creation. Returns immediately with a job_id.

    The actual creation runs in a background task (the import step alone
    can take 30s+ for a 270 MB image). Poll ``/progress/template/{job_id}``.
    """
    background_tasks.add_task(
        admin_svc.create_template_from_qcow2,
        body.template_name,
        body.source_volid,
        body.node,
        disk_storage=body.disk_storage,
        cores=body.cores,
        memory_mb=body.memory_mb,
        disk_gb=body.disk_gb,
        bridge=body.bridge,
        job_id=body.job_id,
    )
    return {
        "job_id": body.job_id,
        "status": "pending",
        "step": "queued",
        "template_name": body.template_name,
        "vmid": None,
        "message": "creation queued; poll /api/v1/admin/progress/template/{job_id}",
    }


@router.post(
    "/set-template/{vmid}",
    summary="Flip template=1 on an existing VM (manual-install path)",
)
async def set_template(vmid: int, body: SetTemplateRequest) -> dict[str, Any]:
    """The wizard uses this when the operator chose 'manual install via ISO'."""
    try:
        await admin_svc.set_template_flag(vmid, body.node)
    except ProxmoxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE error: {exc}",
        ) from exc
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return {"vmid": vmid, "template": True, "node": body.node}


@router.get(
    "/progress/{kind}/{job_id}",
    summary="Poll a setup job's progress",
)
async def get_job_progress(kind: str, job_id: str) -> dict[str, Any]:
    if kind not in ("upload", "template"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown kind: {kind!r} (expected 'upload' or 'template')",
        )
    progress = await admin_svc.get_progress(job_id, kind=kind)
    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job {job_id!r} ({kind}) not found or expired",
        )
    return progress


@router.get(
    "/progress",
    summary="List in-flight setup jobs",
)
async def list_progress() -> dict[str, Any]:
    items = await admin_svc.list_in_progress()
    return {"items": items, "total": len(items)}


@router.get(
    "/drill-template-status",
    summary="Is the canonical drill template (tpl-debian-cloudinit) ready?",
)
async def drill_template_status() -> dict[str, Any]:
    """Mirror of what preflight checks -- exposed here so the wizard's
    final step can show a green checkmark or 'not ready' without the
    operator having to run ``make preflight`` from a terminal.
    """
    from app.services.proxmox import list_templates

    target = "tpl-debian-cloudinit"
    try:
        templates = list_templates()
    except (ProxmoxAPIError, ProxmoxNotConfiguredError) as exc:
        return {
            "ready": False,
            "template": target,
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    match = next((t for t in templates if t.get("name") == target), None)
    if match is None:
        return {
            "ready": False,
            "template": target,
            "available": [t.get("name") for t in templates],
            "error": f"template {target!r} not found on PVE",
        }
    return {"ready": True, "template": target, "vmid": match.get("vmid")}


@router.post(
    "/start-first-drill",
    summary="Convenience: start the first-live-drill scenario",
)
async def start_first_drill(body: StartFirstDrillRequest) -> dict[str, Any]:
    """Run the canonical L1 demo drill."""
    import httpx

    scenario_name = "first-live-drill"
    api_base = os.environ.get("DIVIDE_API_BASE", "http://api:8000")

    async with httpx.AsyncClient(timeout=10.0) as client:
        sr = await client.get(f"{api_base}/api/v1/scenarios")
        if sr.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"could not list scenarios: HTTP {sr.status_code}",
            )
        scenarios = (sr.json().get("items") or [])
        match = next((s for s in scenarios if s.get("name") == scenario_name), None)
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"scenario {scenario_name!r} not in DB -- run 'make sync-scenarios'",
            )

        dr = await client.post(
            f"{api_base}/api/v1/drills",
            json={"scenario_id": match["id"]},
            timeout=body.timeout_s + 5.0,
        )
        if dr.status_code not in (200, 201):
            raise HTTPException(
                status_code=dr.status_code,
                detail=dr.text[:500],
            )
        return dr.json()
