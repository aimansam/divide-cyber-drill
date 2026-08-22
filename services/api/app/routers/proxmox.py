"""Proxmox introspection endpoints.

All endpoints are READ-ONLY (Stage 2). They require PROXMOX_HOST +
PROXMOX_TOKEN_ID + PROXMOX_TOKEN_SECRET in the environment.

Status codes:
  - 200: data returned
  - 502: PVE reachable but call failed (auth, parse, etc.)
  - 503: Proxmox not configured (env vars missing)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.services.proxmox import (
    ProxmoxAPIError,
    ProxmoxNotConfiguredError,
    get_version,
    list_nodes,
    list_storage,
    list_templates,
)

router = APIRouter()


def _is_configured() -> bool:
    """Treat empty env values as 'not configured'."""
    cfg = settings.proxmox
    return bool((cfg.host or "").strip() and (cfg.token_id or "").strip() and cfg.token_secret)


@router.get("/health", summary="Proxmox reachability + version")
async def proxmox_health() -> dict[str, Any]:
    """Return PVE version/release/repoid. Verifies the token works."""
    if not _is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proxmox not configured. Set PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET.",
        )
    try:
        v = get_version()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proxmox unreachable: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # proxmoxer raises ResourceException directly (not wrapped). Catch it
        # here too so we always return a structured error, never a 500.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proxmox error: {type(exc).__name__}: {exc}",
        ) from exc

    return {
        "status": "ok",
        "version": v.get("version"),
        "release": v.get("release"),
        "repoid": v.get("repoid"),
        "host": settings.proxmox.host,
    }


@router.get("/nodes", summary="List Proxmox cluster nodes")
async def list_proxmox_nodes() -> dict[str, Any]:
    if not _is_configured():
        raise HTTPException(status_code=503, detail="Proxmox not configured")
    try:
        items = list_nodes()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Proxmox unreachable: {exc}") from exc
    return {"items": items, "total": len(items)}


@router.get("/storage", summary="List Proxmox storage pools")
async def list_proxmox_storage() -> dict[str, Any]:
    if not _is_configured():
        raise HTTPException(status_code=503, detail="Proxmox not configured")
    try:
        items = list_storage()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Proxmox unreachable: {exc}") from exc
    return {"items": items, "total": len(items)}


@router.get("/templates", summary="List VM templates (optionally by node)")
async def list_proxmox_templates(
    node: str | None = Query(default=None, description="Restrict to this node (default: all nodes)"),
) -> dict[str, Any]:
    if not _is_configured():
        raise HTTPException(status_code=503, detail="Proxmox not configured")
    try:
        items = list_templates(node=node)
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProxmoxAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Proxmox unreachable: {exc}") from exc
    return {"items": items, "total": len(items), "node": node}
