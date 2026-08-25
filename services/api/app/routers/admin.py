"""Admin/setup endpoints for the PVE setup wizard.

Exposed at ``/api/v1/admin/*``. All routes in this module require an
``X-Divide-Token`` header carrying a token whose role is in the
``admin`` allow-list (see :class:`app.core.auth.Role` and
:func:`app.core.auth.require_role`). The gate is registered at the
router level so it's applied uniformly to every endpoint here,
including future additions. Routes:

  * ``GET  /probe``                         — one-shot PVE snapshot
  * ``GET  /storage``                       — list storage pools
  * ``POST /upload-qcow2``                  — upload a cloud image (multipart)
  * ``POST /create-template``               — turn an uploaded qcow2 into a template
  * ``POST /set-template/{vmid}``           — flip template=1 on existing VM
  * ``GET  /progress/{kind}/{job_id}``      — poll a job's status
  * ``GET  /progress``                      — list in-flight jobs
  * ``GET  /drill-template-status``         — does the canonical template exist?
  * ``POST /start-first-drill``             — convenience: run first-live-drill

Security note: this whole module used to be LAN-only. As of L2 2.9
it's hard-gated on admin role. The setup wizard runs in the
operator's browser, mints an admin token via ``tools/issue_token.py``
during step 1, and forwards it on every ``fetch()`` call (see
``docs/SETUP-UI.md``). The user-facing portals (``/portal/app/``)
do not hit any ``/admin/*`` endpoint.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, TokenData, require_role
from app.db.session import get_session
from app.services import admin as admin_svc
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError, list_storage

log = structlog.get_logger()

# Router-level gate: every endpoint in this module requires an admin
# token. ``dependencies=`` is a FastAPI feature that runs the listed
# dependencies before each route handler, but doesn't inject their
# return value into the handler signature. That's exactly what we
# want here -- the handler shouldn't care about the token, only the
# framework's auth check does. The ``require_role`` factory chains
# ``require_token`` underneath, so missing-header is 401 and
# wrong-role is 403.
router = APIRouter(dependencies=[Depends(require_role(Role.ADMIN))])


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


# ---------------------------------------------------------------------------
# F-pve-bridge-wizard: PVE bridge provisioning
# ---------------------------------------------------------------------------
#
# Three endpoints, used by the wizard's Step 0 + by the CLI escape
# hatch (tools/pve_setup_bridges.py):
#
#   GET  /api/v1/admin/expected-bridges   -- pure DB read
#   GET  /api/v1/admin/pve-bridge-status  -- expected vs actual on PVE
#   POST /api/v1/admin/pve-setup-bridges  -- SSH into PVE, write drop-in


class ExpectedBridge(BaseModel):
    name: str
    cidr: str
    gateway_ip: str
    scenario: str
    network: str


class ExpectedBridgesResponse(BaseModel):
    bridges: list[ExpectedBridge]
    conflicts: list[str]


class PveBridgeStatusResponse(BaseModel):
    node: str
    expected: list[str]
    present: list[str]
    missing: list[str]
    ready: bool


class PveSetupBridgesRequest(BaseModel):
    """Body for ``POST /admin/pve-setup-bridges``.

    F-pve-bridge-wizard (SDN variant): the wizard no longer collects
    SSH credentials in the browser. The credentials are whatever was
    saved in Step -1 (``POST /admin/pve-config``) or the env-var
    fallback. The request body only carries operational flags.
    """

    dry_run: bool = Field(
        default=False,
        description=(
            "If true, return the would-be SDN POST list without "
            "actually calling PVE. Useful for the wizard's pre-flight."
        ),
    )
    node: str = Field(
        default="pve",
        max_length=64,
        description=(
            "PVE node name to verify bridges on. Defaults to 'pve'; "
            "override when the runner is pinned to a specific node."
        ),
    )


@router.get(
    "/expected-bridges",
    summary="List the bridges the runner expects on PVE",
)
async def get_expected_bridges(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExpectedBridgesResponse:
    """Pure DB read; no PVE interaction."""
    from app.services.pve_bridges import plan_bridges_from_db

    plan = await plan_bridges_from_db(session)
    return ExpectedBridgesResponse(
        bridges=[
            ExpectedBridge(
                name=b.name,
                cidr=b.cidr,
                gateway_ip=b.gateway_ip,
                scenario=b.scenario,
                network=b.network,
            )
            for b in plan.bridges
        ],
        conflicts=plan.conflicts,
    )


@router.get(
    "/pve-bridge-status",
    summary="Which expected bridges are missing on PVE?",
)
async def get_pve_bridge_status(
    node: str = "pve",
    session: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
) -> PveBridgeStatusResponse:
    """Cross-reference expected with actual PVE state."""
    from app.services.pve_bridges import (
        fetch_present_bridges,
        plan_bridges_from_db,
    )

    plan = await plan_bridges_from_db(session)
    expected = [b.name for b in plan.bridges]
    present = await fetch_present_bridges(node)
    missing = [n for n in expected if n not in present]
    return PveBridgeStatusResponse(
        node=node,
        expected=expected,
        present=sorted(present),
        missing=missing,
        ready=not missing,
    )


# --- SDN readiness probe (F-pve-bridge-wizard, SDN variant) -------------
#
# The wizard's Step 0 needs to know whether the active PVE token has
# ``SDN.Allocate`` permission *before* the operator clicks the
# "Set up bridges" button. This endpoint runs the same probe the
# applier uses, but in read-only form, and returns a structured
# SdnReadiness the UI can render directly.
#
# Returns 200 even on permission failure -- the wizard needs the
# error structure, not a 4xx, so it can render the remediation card.


@router.get(
    "/pve-sdn-status",
    summary="Is PVE reachable, and does the token have SDN.Allocate?",
)
async def get_pve_sdn_status(
    session: Annotated[AsyncSession, Depends(get_session)],
    node: str = "pve",
) -> dict[str, Any]:
    """Probe PVE's SDN state without creating anything.

    Returns the active SDN zone's name, the Vnets already on the
    cluster, and the Vnets that are still missing relative to the
    plan. Permission errors are returned in the body (not as 4xx) so
    the wizard can render the literal PVE message + a copy-pasteable
    ``pveum aclmod`` hint.
    """
    from app.services.pve_bridges import plan_bridges_from_db
    from app.services.pve_sdn import (
        SdnError,
        SdnPermissionError,
        get_active_auth,
        read_sdn_state,
    )

    plan = await plan_bridges_from_db(session)
    expected = [b.name for b in plan.bridges]

    try:
        auth = get_active_auth(node=node)
    except SdnError as exc:
        # No creds configured -- operator must complete Step -1 first.
        return {
            "reachable": False,
            "zone_present": False,
            "zone_name": "divide",
            "vnets_present": [],
            "vnets_missing": expected,
            "error": str(exc),
            "pveum_hint": None,
            "required_role": None,
        }

    try:
        readiness = await read_sdn_state(auth=auth, expected_vnets=expected)
        return {
            "reachable": readiness.reachable,
            "zone_present": readiness.zone_present,
            "zone_name": readiness.zone_name,
            "vnets_present": readiness.vnets_present,
            "vnets_missing": readiness.vnets_missing,
            "error": readiness.error,
            "pveum_hint": readiness.pveum_hint,
            "required_role": readiness.required_role,
        }
    except SdnPermissionError as exc:
        # Shouldn't happen (read_sdn_state catches it) but defensive.
        return {
            "reachable": True,
            "zone_present": False,
            "zone_name": "divide",
            "vnets_present": [],
            "vnets_missing": expected,
            "error": str(exc),
            "pveum_hint": exc.pveum_hint,
            "required_role": exc.required_role,
        }
    except SdnError as exc:
        log.warning("pve_sdn.status_failed", error=str(exc))
        return {
            "reachable": False,
            "zone_present": False,
            "zone_name": "divide",
            "vnets_present": [],
            "vnets_missing": expected,
            "error": str(exc),
            "pveum_hint": None,
            "required_role": None,
        }


class PveSetupBridgesResponse(BaseModel):
    ok: bool
    added: list[str]
    already_present: list[str]
    reload_ok: bool
    reload_method: str
    verify_ok: bool
    config_path: str
    dry_run: bool
    message: str


@router.post(
    "/pve-setup-bridges",
    summary="Create the F3 bridges on PVE via SDN",
)
async def post_pve_setup_bridges(
    body: PveSetupBridgesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PveSetupBridgesResponse:
    """Drive the PVE SDN controller to realize the bridge plan.

    Uses the credentials already saved in Step -1 of the wizard
    (``pve_config`` DB row, with env-var fallback) -- there is no
    longer any need for the operator to supply SSH credentials in the
    browser. PVE 8.1+ exposes ``/cluster/sdn/{zones,vnets}`` which
    creates Linux bridges purely via API; PVE then propagates them to
    every node in the cluster.

    Errors:
      * 409 -- bridge plan has conflicts (resolve scenario CIDRs first)
      * 502 -- PVE rejected the SDN POST (e.g. token lacks ``SDN.Allocate``)
      * 503 -- no PVE creds configured yet (complete Step -1 first)
    """
    from app.services.pve_bridges import (
        BridgePlanError,
        plan_bridges_from_db,
    )
    from app.services.pve_sdn import (
        SdnError,
        SdnPermissionError,
        apply_sdn_plan,
        get_active_auth,
        to_apply_result,
    )

    plan = await plan_bridges_from_db(session)
    if plan.conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "bridge plan has conflicts; resolve before applying: "
                + "; ".join(plan.conflicts)
            ),
        )
    if not plan.bridges:
        return PveSetupBridgesResponse(
            ok=True,
            added=[],
            already_present=[],
            reload_ok=True,
            reload_method="none",
            verify_ok=True,
            config_path="",
            dry_run=body.dry_run,
            message="no bridges required by any active scenario",
        )

    try:
        auth = get_active_auth(node=body.node)
    except SdnError as exc:
        # No creds yet -- wizard must complete Step -1 first.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{exc} -- complete wizard Step -1 (PVE credentials) "
                "or set PROXMOX_* env vars in deploy/.env."
            ),
        ) from exc

    if body.dry_run:
        # Don't call PVE; just report what would happen.
        sdn = await apply_sdn_plan(plan, auth=auth, dry_run=True)
        return PveSetupBridgesResponse(
            ok=True,
            added=sdn.vnets_created,
            already_present=sdn.vnets_already_present,
            reload_ok=True,
            reload_method="sdn-dry-run",
            verify_ok=True,
            config_path=sdn.raw_responses[0].get("would_create_zone", "divide"),
            dry_run=True,
            message=(
                f"dry_run: would create {len(sdn.vnets_already_present)} "
                f"Vnet(s) in zone 'divide' on PVE {auth.base_url}"
            ),
        )

    try:
        sdn = await apply_sdn_plan(plan, auth=auth)
    except SdnPermissionError as exc:
        # PVE said "Permission check failed (/sdn/zones, SDN.Allocate)".
        # Surface the literal PVE message + a copy-pasteable pveum hint
        # so the wizard can render a remediation card.
        log.warning(
            "pve_sdn.apply.permission_denied",
            host=auth.base_url,
            role=exc.required_role,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": str(exc),
                "required_role": exc.required_role,
                "pveum_hint": exc.pveum_hint,
                "pve_path": exc.pve_path,
            },
        ) from exc
    except SdnError as exc:
        log.warning(
            "pve_sdn.apply.failed",
            host=auth.base_url,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE rejected the SDN request: {exc}",
        ) from exc
    except BridgePlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    result = to_apply_result(plan, sdn)
    return PveSetupBridgesResponse(
        ok=result.reload_ok and result.verify_ok,
        added=result.added,
        already_present=result.already_present,
        reload_ok=result.reload_ok,
        reload_method=result.reload_method,
        verify_ok=result.verify_ok,
        config_path=result.config_path,
        dry_run=False,
        message=(
            f"created SDN zone + {len(result.added)} Vnet(s); "
            f"propagation {'ok' if result.verify_ok else 'TIMED OUT'} "
            f"after {sdn.propagation_wait_s:.1f}s"
        ),
    )
