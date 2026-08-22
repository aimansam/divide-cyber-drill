"""Proxmox introspection endpoints (Phase 0: stub unless configured)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.services.proxmox import ProxmoxNotConfiguredError, get_proxmox_client

router = APIRouter()


@router.get("/health", summary="Proxmox reachability check")
async def proxmox_health() -> dict:
    if not settings.proxmox.host:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proxmox not configured. Set PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET.",
        )
    try:
        client = get_proxmox_client()
        version = client.version()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Proxmox unreachable: {exc.__class__.__name__}: {exc}") from exc

    return {"status": "ok", "version": version.get("version"), "release": version.get("release")}


@router.get("/nodes", summary="List Proxmox nodes (stub unless configured)")
async def list_nodes() -> dict:
    if not settings.proxmox.host:
        raise HTTPException(status_code=503, detail="Proxmox not configured")
    try:
        client = get_proxmox_client()
        nodes = client.nodes.get()
    except ProxmoxNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"items": [{"node": n["node"], "status": n["status"], "level": n.get("level")} for n in nodes]}
