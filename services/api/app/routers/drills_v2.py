"""Drill router for OxBlood v2.

Provides endpoints for drill management, lifecycle, participants, teams, and announcements.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models_oxblood import DrillStatus
from app.services.drill_service import (
    list_drills, get_drill, create_drill, update_drill, cancel_drill,
    start_drill, pause_drill, resume_drill, stop_drill,
    list_drill_participants, add_participant, remove_participant,
    list_drill_teams, add_team, remove_team,
    list_drill_announcements, create_announcement,
    list_drill_objectives, create_drill_objective,
    list_drill_scenarios, link_scenario,
)

router = APIRouter(prefix="/api/v2/drills", tags=["Drills v2"])


# ============================================================================
# Pydantic Models
# ============================================================================

class DrillCreate(BaseModel):
    title: str
    description: Optional[str] = None
    lab_id: Optional[int] = None
    drill_type: str = "individual"
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    duration_limit_minutes: Optional[int] = None
    max_participants: Optional[int] = None
    rules: Optional[dict] = None
    environment_config: Optional[dict] = None


class DrillUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    duration_limit_minutes: Optional[int] = None
    max_participants: Optional[int] = None
    rules: Optional[dict] = None
    environment_config: Optional[dict] = None


class ParticipantAdd(BaseModel):
    user_id: int
    team_id: Optional[int] = None
    role: str = "participant"


class TeamAdd(BaseModel):
    team_id: int
    team_side: Optional[str] = None


class AnnouncementCreate(BaseModel):
    title: str
    content: str
    priority: str = "normal"


class ObjectiveCreate(BaseModel):
    title: str
    description: Optional[str] = None
    points: int = 0
    side: Optional[str] = None
    sort_order: int = 0


class ScenarioLink(BaseModel):
    lab_id: int
    scenario_config: Optional[dict] = None


# ============================================================================
# Helper
# ============================================================================

def drill_to_dict(drill) -> dict:
    """Convert drill to dict."""
    return {
        "id": drill.id,
        "title": drill.title,
        "description": drill.description,
        "lab_id": drill.lab_id,
        "drill_type": drill.drill_type,
        "status": drill.status.value if hasattr(drill.status, "value") else drill.status,
        "scheduled_start_at": drill.scheduled_start_at.isoformat() if drill.scheduled_start_at else None,
        "scheduled_end_at": drill.scheduled_end_at.isoformat() if drill.scheduled_end_at else None,
        "actual_start_at": drill.actual_start_at.isoformat() if drill.actual_start_at else None,
        "actual_end_at": drill.actual_end_at.isoformat() if drill.actual_end_at else None,
        "duration_limit_minutes": drill.duration_limit_minutes,
        "max_participants": drill.max_participants,
        "rules": drill.rules,
        "environment_config": drill.environment_config,
        "created_by": drill.created_by,
        "created_at": drill.created_at.isoformat() if drill.created_at else None,
        "updated_at": drill.updated_at.isoformat() if drill.updated_at else None,
    }


# ============================================================================
# Drill CRUD
# ============================================================================

@router.get("")
async def get_drills(
    status: Optional[DrillStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """List drills with optional status filter."""
    drills = await list_drills(db, status=status, skip=skip, limit=limit)
    return {"drills": [drill_to_dict(drill) for drill in drills]}


@router.post("")
async def post_drill(
    data: DrillCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new drill."""
    try:
        drill = await create_drill(db, **data.model_dump())
        return {"message": "Drill created", "drill_id": drill.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{drill_id}/announcements/{announcement_id}")
async def remove_announcement(
    drill_id: int,
    announcement_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Delete a drill announcement."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    from app.services.drill_service import delete_announcement as svc_delete_announcement
    deleted = await svc_delete_announcement(db, announcement_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement deleted"}


@router.get("/{drill_id}")
async def get_drill_endpoint(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get drill details."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    return drill_to_dict(drill)


@router.put("/{drill_id}")
async def put_drill(
    drill_id: int,
    data: DrillUpdate,
    db: AsyncSession = Depends(get_session),
):
    """Update a drill."""
    drill = await update_drill(db, drill_id, **data.model_dump(exclude_none=True))
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    return {"message": "Drill updated"}


@router.delete("/{drill_id}")
async def delete_drill(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Cancel a drill (soft delete)."""
    drill = await cancel_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    return {"message": "Drill cancelled"}


# ============================================================================
# Drill Lifecycle
# ============================================================================

@router.post("/{drill_id}/start")
async def start_drill_endpoint(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Start a drill."""
    try:
        drill = await start_drill(db, drill_id)
        if not drill:
            raise HTTPException(status_code=404, detail="Drill not found")
        return {"message": "Drill started", "status": drill.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{drill_id}/pause")
async def pause_drill_endpoint(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Pause a drill."""
    try:
        drill = await pause_drill(db, drill_id)
        if not drill:
            raise HTTPException(status_code=404, detail="Drill not found")
        return {"message": "Drill paused", "status": drill.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{drill_id}/resume")
async def resume_drill_endpoint(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Resume a paused drill."""
    try:
        drill = await resume_drill(db, drill_id)
        if not drill:
            raise HTTPException(status_code=404, detail="Drill not found")
        return {"message": "Drill resumed", "status": drill.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{drill_id}/stop")
async def stop_drill_endpoint(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Stop a drill."""
    try:
        drill = await stop_drill(db, drill_id)
        if not drill:
            raise HTTPException(status_code=404, detail="Drill not found")
        return {"message": "Drill stopped", "status": drill.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Participants
# ============================================================================

@router.get("/{drill_id}/participants")
async def get_participants(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all participants in a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    participants = await list_drill_participants(db, drill_id)
    return {
        "participants": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "team_id": p.team_id,
                "role": p.role,
                "status": p.status,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None,
            }
            for p in participants
        ]
    }


@router.post("/{drill_id}/participants")
async def post_participant(
    drill_id: int,
    data: ParticipantAdd,
    db: AsyncSession = Depends(get_session),
):
    """Add a participant to a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    try:
        participant = await add_participant(
            db, drill_id, data.user_id, data.team_id, data.role
        )
        return {"message": "Participant added", "participant_id": participant.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{drill_id}/participants/{user_id}")
async def delete_participant(
    drill_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Remove a participant from a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    removed = await remove_participant(db, drill_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Participant not found")
    return {"message": "Participant removed"}


# ============================================================================
# Teams
# ============================================================================

@router.get("/{drill_id}/teams")
async def get_teams(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all teams in a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    teams = await list_drill_teams(db, drill_id)
    return {
        "teams": [
            {
                "id": t.id,
                "team_id": t.team_id,
                "team_side": t.team_side,
                "registered_at": t.registered_at.isoformat() if t.registered_at else None,
            }
            for t in teams
        ]
    }


@router.post("/{drill_id}/teams")
async def post_team(
    drill_id: int,
    data: TeamAdd,
    db: AsyncSession = Depends(get_session),
):
    """Add a team to a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    try:
        team = await add_team(db, drill_id, data.team_id, data.team_side)
        return {"message": "Team added", "drill_team_id": team.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{drill_id}/teams/{team_id}")
async def delete_team(
    drill_id: int,
    team_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Remove a team from a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    removed = await remove_team(db, drill_id, team_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"message": "Team removed"}


# ============================================================================
# Announcements
# ============================================================================

@router.get("/{drill_id}/announcements")
async def get_announcements(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all announcements for a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    announcements = await list_drill_announcements(db, drill_id)
    return {
        "announcements": [
            {
                "id": a.id,
                "title": a.title,
                "content": a.content,
                "priority": a.priority,
                "published_by": a.published_by,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in announcements
        ]
    }


@router.post("/{drill_id}/announcements")
async def post_announcement(
    drill_id: int,
    data: AnnouncementCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a drill announcement."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    try:
        announcement = await create_announcement(
            db, drill_id, data.title, data.content, data.priority
        )
        return {"message": "Announcement created", "announcement_id": announcement.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Objectives
# ============================================================================

@router.get("/{drill_id}/objectives")
async def get_objectives(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all objectives for a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    objectives = await list_drill_objectives(db, drill_id)
    return {
        "objectives": [
            {
                "id": o.id,
                "title": o.title,
                "description": o.description,
                "points": o.points,
                "side": o.side,
                "sort_order": o.sort_order,
            }
            for o in objectives
        ]
    }


@router.post("/{drill_id}/objectives")
async def post_objective(
    drill_id: int,
    data: ObjectiveCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a drill objective."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    try:
        objective = await create_drill_objective(
            db, drill_id, data.title, data.description, data.points, data.side, data.sort_order
        )
        return {"message": "Objective created", "objective_id": objective.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Scenarios
# ============================================================================

@router.get("/{drill_id}/scenarios")
async def get_scenarios(
    drill_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all scenarios linked to a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    scenarios = await list_drill_scenarios(db, drill_id)
    return {
        "scenarios": [
            {
                "id": s.id,
                "lab_id": s.lab_id,
                "scenario_config": s.scenario_config,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in scenarios
        ]
    }


@router.post("/{drill_id}/scenarios")
async def post_scenario(
    drill_id: int,
    data: ScenarioLink,
    db: AsyncSession = Depends(get_session),
):
    """Link a lab scenario to a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")
    try:
        scenario = await link_scenario(db, drill_id, data.lab_id, data.scenario_config)
        return {"message": "Scenario linked", "scenario_id": scenario.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
