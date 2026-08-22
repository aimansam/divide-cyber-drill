"""Drill lifecycle endpoints (Phase 0: stub)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.get("", summary="List drills (stub)")
async def list_drills() -> dict:
    return {"items": [], "total": 0, "phase": 0}


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED, summary="Start a drill (stub)")
async def start_drill() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Drill orchestration lands in Phase 1. See docs/PLAN.md §5.2. "
            "Proxmox integration requires PROXMOX_HOST and a token."
        ),
    )
