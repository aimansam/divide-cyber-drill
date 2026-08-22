"""Scenario CRUD endpoints (Phase 0: stub)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.get("", summary="List scenarios (stub)")
async def list_scenarios() -> dict:
    """Phase 0 stub: returns an empty list. Implementation lands in Phase 1."""
    return {"items": [], "total": 0, "phase": 0}


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED, summary="Create scenario (stub)")
async def create_scenario() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Scenario CRUD lands in Phase 1. See docs/PLAN.md §5.4.",
    )
