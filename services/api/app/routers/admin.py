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

from app.core.auth import Role, TokenData, current_token, require_role
from app.db.session import get_session
from app.services import admin as admin_svc
from app.services import pve_config as pve_config_svc
from app.services import orphan_cleanup as orphan_svc
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError, list_storage
from app.runners.runner import build_runner

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
    """Body for ``POST /admin/start-first-drill``.

    Q14: added optional ``team`` field so the operator can name the
    team running the drill (matches POST /drills's team binding).
    """

    timeout_s: int = 300
    team: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Optional team name for the run (e.g. 'blue', 'red-team-A'). "
            "Matches the ``team`` field accepted by POST /api/v1/drills."
        ),
    )


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
async def start_first_drill(
    body: StartFirstDrillRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    token=Depends(current_token),
) -> dict[str, Any]:
    """Run the canonical L1 demo drill.

    Q14: was a loopback HTTP call to ``/api/v1/drills`` which
    required ``X-Divide-Token`` to be forwarded. The forward
    was missing, so every call returned a doubly-nested 401.
    Rewritten to call the runner in-process:
      * look up the scenario in the same DB session,
      * build a RunRequest with the caller's token.sub,
      * call ``runner.start_run()`` directly,
      * return the result RunResult as JSON.

    This keeps the wizard's "Start first drill" button working
    without leaking auth tokens into a self-call.
    """
    from app.runners.runner import (
        RunRequest,
        RunnerError,
        build_runner,
    )

    from sqlalchemy import select

    from app.db import models as db_models
    from app.services.proxmox import ProxmoxAPIError
    from app.services.pve_sdn import SdnPermissionError

    scenario_name = "first-live-drill"
    scenario = (
        await session.execute(
            select(db_models.Scenario).where(
                db_models.Scenario.name == scenario_name,
                db_models.Scenario.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"scenario {scenario_name!r} not in DB or is archived -- "
                "run 'make sync-scenarios' or restore it first"
            ),
        )

    runner = build_runner()
    try:
        result = await runner.start_run(
            RunRequest(
                scenario_id=scenario.id,
                started_by=token.sub,
                exercise_id=None,
                team=body.team,
                template_id=None,
            ),
            session,
        )
    except RunnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except SdnPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": str(exc),
                "required_role": getattr(exc, "required_role", None),
                "pveum_hint": getattr(exc, "pveum_hint", None),
                "pve_path": getattr(exc, "pve_path", None),
            },
        ) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE unreachable: {exc}",
        ) from exc
    return {
        "run_id": result.run_id,
        "status": result.status.value,
        "scenario_id": scenario.id,
        "scenario_name": scenario_name,
        "team": body.team,
        "started_by": token.sub,
    }


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
    summary="Create the F3 bridges on PVE",
)
async def post_pve_setup_bridges(
    body: PveSetupBridgesRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PveSetupBridgesResponse:
    """Realize the bridge plan on PVE.

    The default implementation (PVE 9 single-node friendly) POSTs
    directly to PVE's node-level network API
    (``/nodes/{n}/network``) which creates Linux bridges on the node
    without requiring an external SDN controller. Set
    ``method="sdn"`` in the request to fall back to the legacy
    SDN zone/vnet path (needs ``SDN.Allocate`` and a controller
    that materializes the bridges on PVE 9).

    Uses the credentials already saved in Step -1 of the wizard
    (``pve_config`` DB row, with env-var fallback).

    Errors:
      * 403 -- PVE rejected the create POST due to a missing
        privilege (``Sys.Modify`` for the direct path,
        ``SDN.Allocate`` for the SDN path). The response carries a
        copy-pasteable ``pveum`` remediation hint.
      * 409 -- bridge plan has conflicts (resolve scenario CIDRs first)
      * 502 -- PVE rejected the request for a non-permission reason.
      * 503 -- no PVE creds configured yet (complete Step -1 first)
    """
    from app.services.pve_bridges import (
        BridgePlanError,
        plan_bridges_from_db,
    )
    from app.services.pve_sdn import (
        SdnError,
        SdnPermissionError,
        apply_direct_plan,
        get_active_auth,
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
        sdn = await apply_direct_plan(plan, auth=auth, dry_run=True)
        n = len(sdn.vnets_already_present)
        return PveSetupBridgesResponse(
            ok=True,
            added=sdn.vnets_created,
            already_present=sdn.vnets_already_present,
            reload_ok=True,
            reload_method="direct-dry-run",
            verify_ok=True,
            config_path=f"/nodes/{auth.node}/network",
            dry_run=True,
            message=(
                f"dry_run: would create {n} bridge(s) on PVE node "
                f"{auth.node} ({auth.base_url})"
            ),
        )

    try:
        sdn = await apply_direct_plan(plan, auth=auth)
    except SdnPermissionError as exc:
        # PVE said "Permission check failed (/nodes/{n}, Sys.Modify)"
        # (or /sdn if method=sdn). Surface the literal PVE message
        # + a copy-pasteable pveum hint so the wizard can render a
        # remediation card.
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
            detail=f"PVE rejected the request: {exc}",
        ) from exc
    except BridgePlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    reload_method = "direct" if sdn.vnets_created else "direct-noop"
    return PveSetupBridgesResponse(
        ok=sdn.propagate_ok,
        added=sdn.vnets_created,
        already_present=sdn.vnets_already_present,
        reload_ok=sdn.propagate_ok,
        reload_method=reload_method,
        verify_ok=sdn.propagate_ok,
        config_path=f"/nodes/{auth.node}/network",
        dry_run=False,
        message=(
            f"created {len(sdn.vnets_created)} Linux bridge(s) on PVE "
            f"node {auth.node}; propagation "
            f"{'ok' if sdn.propagate_ok else 'TIMED OUT'} after "
            f"{sdn.propagation_wait_s:.1f}s"
        ),
    )
# ---------------------------------------------------------------------------
# PVE runtime config (day-1 web setup; precedes Step0 in the wizard)
# ---------------------------------------------------------------------------
#
# These three endpoints let the onboarding wizard collect the PVE host /
# user / token from the browser instead of requiring ``deploy/.env``
# edits + container restart. ``POST`` probes PVE first (so a typo is
# surfaced before commit), then writes the singleton row in
# ``pve_config``. The very next PVE call (admin probe, run start,
# template upload, etc.) honors the new credentials because the
# admin router calls ``set_db_overlay`` after the commit, which
# drops both ``get_proxmox_client``'s LRU cache and the TTL cache.
#
# ``GET`` returns either the DB row (token_secret masked) or the env-var
# fallback if no row exists, with ``source`` set accordingly so the
# wizard can render a banner.
#
# ``DELETE`` drops the DB row and reverts to env-var resolution. Useful
# as an escape hatch: an operator who wants to "go back to .env" can do
# it from the admin UI without touching the host.


class PveConfigPayload(BaseModel):
    """Request body for ``POST /api/v1/admin/pve-config``.

    The token_secret is in the clear because we need to hand it to
    proxmoxer; the response always masks it. We never log it.
    """

    host: str = Field(..., min_length=1, max_length=255, description="e.g. https://192.168.0.10")
    port: int = Field(default=8006, ge=1, le=65535)
    user: str = Field(..., min_length=1, max_length=255, description="e.g. divide@pve@pam")
    token_id: str = Field(..., min_length=1, max_length=255, description="e.g. divide@pve@pam!drill-token")
    token_secret: str = Field(..., min_length=1, max_length=255)
    verify_ssl: bool = Field(default=False, description="False for self-signed certs (default for home/lab PVE)")
    node: str | None = Field(default=None, max_length=64, description="Optional node name; auto-detected when omitted")


@router.get(
    "/pve-config",
    summary="Get the active PVE connection config (DB or env).",
    description=(
        "Returns the singleton PVE config the API is currently using. "
        "If a row exists in `pve_config`, that's returned with "
        "`source=db` and `token_secret` masked as `***`. If no row "
        "exists, the env-var fallback is returned with `source=env` "
        "and `token_secret=***` (we don't have the env value here)."
    ),
)
async def get_pve_config(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    row = await pve_config_svc.get_config(db)
    if row is not None:
        return row.to_public_dict()
    return pve_config_svc.env_source_dict()


@router.post(
    "/pve-config",
    summary="Write (or replace) the PVE runtime config.",
    description=(
        "Probes PVE with the supplied credentials first; commits only "
        "if the probe succeeds. After commit, the in-process overlay "
        "is refreshed so the next PVE call picks up the new creds -- "
        "no container restart required. Use `DELETE` to revert to the "
        "env-var fallback."
    ),
)
async def post_pve_config(
    body: PveConfigPayload,
    db: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[TokenData, Depends(require_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Validate, probe, persist, hydrate.

    Status codes:
      * 200 -- creds accepted, row written
      * 400 -- validation failed (Pydantic or service-level)
      * 502 -- PVE rejected the creds (probe-before-commit caught it)
    """
    # Write the new creds into the overlay so the probe uses them
    # (without committing to the DB yet). If the probe fails the
    # operator sees the actual PVE error and we abort -- no DB churn.
    from app.services.proxmox import set_db_overlay

    set_db_overlay(
        {
            "host": body.host,
            "port": body.port,
            "user": body.user,
            "token_id": body.token_id,
            "token_secret": body.token_secret,
            "verify_ssl": body.verify_ssl,
            "node": body.node,
        }
    )
    from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError, get_version

    try:
        get_version()
    except (ProxmoxNotConfiguredError, ProxmoxAPIError) as exc:
        # Probe failed. Roll overlay back to None so the next call
        # goes to env vars (whichever was active before). Better than
        # leaving a partial overlay hanging around.
        set_db_overlay(None)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE rejected the supplied credentials: {exc}",
        ) from exc
    # Probe ok. Persist.
    try:
        row = await pve_config_svc.upsert_config(
            db,
            host=body.host,
            port=body.port,
            user=body.user,
            token_id=body.token_id,
            token_secret=body.token_secret,
            verify_ssl=body.verify_ssl,
            node=body.node,
            updated_by=token.sub,
        )
    except pve_config_svc.PveConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    log.info(
        "pve_config.upsert",
        host=body.host,
        user=body.user,
        token_id=body.token_id,
        updated_by=token.sub,
    )
    return {
        **row.to_public_dict(),
        "probed": True,
        "message": "PVE accepted the credentials. Wizard can advance.",
    }


@router.delete(
    "/pve-config",
    summary="Drop the PVE config row; revert to env-var resolution.",
    description=(
        "Useful for operators who want to 'go back to deploy/.env' "
        "without touching the host. After delete, the API falls back "
        "to the `PROXMOX_*` env vars on the next PVE call. No-op if "
        "no row exists."
    ),
)
async def delete_pve_config(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    deleted = await pve_config_svc.delete_config(db)
    # Refresh overlay so the next PVE call goes back to env.
    from app.services.proxmox import set_db_overlay

    set_db_overlay(None)
    log.info("pve_config.delete", deleted=deleted)
    return {
        "deleted": deleted,
        "message": (
            "DB row deleted; API now resolves PVE creds from "
            "PROXMOX_* env vars."
            if deleted
            else "No DB row to delete; API is already on env-var fallback."
        ),
    }


# -- orphan-asset janitor (Q22) -------------------------------------------
#
# Iterates Asset rows where status == ORPHANED (set by the Q17 teardown
# loop when destroy_vm failed) and retries the destroy. Two flavours:
#
#   * GET  /assets/orphans   -- dry-run preview, used by the UI's modal
#   * POST /assets/cleanup   -- actually calls destroy_vm. Idempotent.
#
# Both honour the same skip rules (grace period, live runs, missing
# VMID). The runner gives us the same adapter that started the drill,
# so credentials + node config match.

from app.db.models import AssetStatus  # noqa: E402


class OrphanCandidate(BaseModel):
    """One asset row that's a cleanup candidate."""

    asset_id: int
    run_id: int
    run_status: str
    role: str
    pve_vmid: int | None
    pve_node: str | None
    error: str | None
    age_seconds: int


class OrphanListResponse(BaseModel):
    items: list[OrphanCandidate]
    total: int


class CleanupFailureItem(BaseModel):
    asset_id: int
    run_id: int
    pve_vmid: int | None
    error: str


class CleanupRequest(BaseModel):
    """Body for POST /assets/cleanup.

    ``asset_ids``: when set, only these ids are considered; ``null``
    means "every orphan" (subject to grace + run-status filters).
    ``grace_minutes``: skip orphans younger than this; default 5.
    """

    asset_ids: list[int] | None = None
    grace_minutes: int = Field(default=5, ge=0, le=1440)


class CleanupResponse(BaseModel):
    scanned: int
    destroyed: int
    failed: list[CleanupFailureItem]
    skipped_running: list[int]


@router.get(
    "/assets/orphans",
    summary="List Asset rows in ORPHANED state (dry-run cleanup preview)",
)
async def list_orphan_assets(
    db: Annotated[AsyncSession, Depends(get_session)],
    grace_minutes: int = 5,
    asset_ids: str | None = None,
    token: Annotated[TokenData, Depends(require_role(Role.ADMIN))] = None,
) -> OrphanListResponse:
    """Preview what ``POST /assets/cleanup`` would do.

    ``asset_ids`` is a comma-separated list (query string), ``null``
    means every orphan.
    """
    ids: list[int] | None = None
    if asset_ids:
        try:
            ids = [int(s) for s in asset_ids.split(",") if s.strip()]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"asset_ids must be comma-separated ints: {exc}",
            ) from exc
    candidates = await orphan_svc.list_orphans(
        db, grace_minutes=grace_minutes, asset_ids=ids
    )
    return OrphanListResponse(
        items=[
            OrphanCandidate(
                asset_id=c.asset_id,
                run_id=c.run_id,
                run_status=c.run_status,
                role=c.role,
                pve_vmid=c.pve_vmid,
                pve_node=c.pve_node,
                error=c.error,
                age_seconds=c.age_seconds,
            )
            for c in candidates
        ],
        total=len(candidates),
    )


@router.post(
    "/assets/cleanup",
    summary="Retry destroy_vm on ORPHANED assets (idempotent)",
)
async def cleanup_orphan_assets(
    body: CleanupRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[TokenData, Depends(require_role(Role.ADMIN))] = None,
) -> CleanupResponse:
    """Best-effort destroy every orphan matching the request body.

    Successful releases flip ``Asset.status`` to STOPPED and stamp
    ``cleaned_at``; failed retries stay ORPHANED with a fresh error.
    Each success writes one ``asset.cleaned`` audit row with
    ``actor = token.sub``.
    """
    actor = getattr(token, "sub", "unknown") if token else "unknown"
    runner = build_runner()
    adapter = runner._adapter  # noqa: SLF001 -- janitor uses the same
    # adapter that runs drills, so credentials + node match.
    try:
        result = await orphan_svc.cleanup_orphans(
            db,
            adapter,
            actor,
            grace_minutes=body.grace_minutes,
            asset_ids=body.asset_ids,
        )
    except ProxmoxAPIError as exc:
        # PVE-side failure: return 502 rather than crashing 500.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PVE unreachable: {exc}",
        ) from exc
    return CleanupResponse(
        scanned=result.scanned,
        destroyed=result.destroyed,
        failed=[
            CleanupFailureItem(
                asset_id=f.asset_id,
                run_id=f.run_id,
                pve_vmid=f.pve_vmid,
                error=f.error,
            )
            for f in result.failed
        ],
        skipped_running=result.skipped_running,
    )


# -- service-status aggregator --------------------------------------------
#
# Aggregates PVE / wg-easy / WireGuard env / disk / audit recency into a
# single read-only snapshot for the Config tab's "Deployment status"
# panel. Authenticated (admin or lead) so we don't leak env-derived
# signals to anonymous callers, but no role gate beyond login -- the
# existing probe endpoints have the same posture.

from app.services import service_status as service_status_svc  # noqa: E402


@router.get(
    "/service-status",
    summary="Aggregated runtime status for the Config tab's deployment panel",
)
async def get_service_status(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Read-only aggregator. Fails soft: one bad probe never blocks
    the rest. Polled on every Config tab Refresh.
    """
    return await service_status_svc.get_service_status(db)
