"""Drill service for OxBlood v2.

Handles drill CRUD, lifecycle management, participants, teams, and announcements.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_oxblood import (
    Drill, DrillStatus, DrillParticipant, DrillTeam, DrillAnnouncement,
    DrillObjective, DrillScenario, Lab, Team, User,
)
import re


# ============================================================================
# Input Sanitization Helper
# ============================================================================

def _sanitize_text(text: str) -> str:
    """Remove potentially dangerous HTML/script tags from text."""
    if not text:
        return text
    # Remove script tags and their content
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove event handlers (onclick, onerror, etc.)
    text = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+on\w+\s*=\s*\S+', '', text, flags=re.IGNORECASE)
    # Remove javascript: URLs
    text = re.sub(r'javascript\s*:', '', text, flags=re.IGNORECASE)
    # Remove iframe, object, embed tags
    text = re.sub(r'<(iframe|object|embed|form|input|button)[^>]*>.*?</\1>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<(iframe|object|embed|form|input|button)[^>]*/?\s*>', '', text, flags=re.IGNORECASE)
    return text.strip()


# ============================================================================
# Drill CRUD
# ============================================================================

async def list_drills(
    db: AsyncSession,
    status: Optional[DrillStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Drill]:
    """List drills with optional status filter."""
    query = select(Drill).where(Drill.deleted_at.is_(None))
    if status:
        query = query.where(Drill.status == status)
    query = query.order_by(Drill.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Get a drill by ID."""
    result = await db.execute(
        select(Drill).where(Drill.id == drill_id, Drill.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_drill(
    db: AsyncSession,
    title: str,
    description: Optional[str] = None,
    lab_id: Optional[int] = None,
    drill_type: str = "individual",
    scheduled_start_at: Optional[datetime] = None,
    scheduled_end_at: Optional[datetime] = None,
    duration_limit_minutes: Optional[int] = None,
    max_participants: Optional[int] = None,
    rules: Optional[dict] = None,
    environment_config: Optional[dict] = None,
    created_by: Optional[int] = None,
) -> Drill:
    """Create a new drill."""
    # Validate input
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    if len(title) > 255:
        raise ValueError("Title cannot exceed 255 characters")
    if duration_limit_minutes is not None and duration_limit_minutes <= 0:
        raise ValueError("Duration limit must be positive")
    if max_participants is not None and max_participants <= 0:
        raise ValueError("Max participants must be positive")
    
    # Sanitize text fields to prevent XSS
    title = _sanitize_text(title)
    description = _sanitize_text(description) if description else description
    
    drill = Drill(
        title=title,
        description=description,
        lab_id=lab_id,
        drill_type=drill_type,
        status=DrillStatus.SCHEDULED,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        duration_limit_minutes=duration_limit_minutes,
        max_participants=max_participants,
        rules=rules or {},
        environment_config=environment_config or {},
        created_by=created_by,
    )
    db.add(drill)
    await db.commit()
    await db.refresh(drill)
    return drill


async def update_drill(db: AsyncSession, drill_id: int, **kwargs) -> Optional[Drill]:
    """Update a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    for key, value in kwargs.items():
        if hasattr(drill, key) and value is not None:
            setattr(drill, key, value)
    await db.commit()
    await db.refresh(drill)
    return drill


async def cancel_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Cancel a drill (soft delete)."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    drill.status = DrillStatus.CANCELLED
    drill.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(drill)
    return drill


# ============================================================================
# Drill Lifecycle
# ============================================================================

async def start_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Start a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    if drill.status != DrillStatus.SCHEDULED:
        raise ValueError(f"Cannot start drill in {drill.status} state")
    drill.status = DrillStatus.ACTIVE
    drill.actual_start_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(drill)
    return drill


async def pause_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Pause a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    if drill.status != DrillStatus.ACTIVE:
        raise ValueError(f"Cannot pause drill in {drill.status} state")
    drill.status = DrillStatus.PAUSED
    await db.commit()
    await db.refresh(drill)
    return drill


async def resume_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Resume a paused drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    if drill.status != DrillStatus.PAUSED:
        raise ValueError(f"Cannot resume drill in {drill.status} state")
    drill.status = DrillStatus.ACTIVE
    await db.commit()
    await db.refresh(drill)
    return drill


async def stop_drill(db: AsyncSession, drill_id: int) -> Optional[Drill]:
    """Stop a drill."""
    drill = await get_drill(db, drill_id)
    if not drill:
        return None
    if drill.status not in [DrillStatus.ACTIVE, DrillStatus.PAUSED]:
        raise ValueError(f"Cannot stop drill in {drill.status} state")
    drill.status = DrillStatus.COMPLETED
    drill.actual_end_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(drill)
    return drill


# ============================================================================
# Participants
# ============================================================================

async def list_drill_participants(db: AsyncSession, drill_id: int) -> list[DrillParticipant]:
    """List all participants in a drill."""
    result = await db.execute(
        select(DrillParticipant)
        .where(DrillParticipant.drill_id == drill_id)
        .order_by(DrillParticipant.joined_at)
    )
    return result.scalars().all()


async def add_participant(
    db: AsyncSession,
    drill_id: int,
    user_id: int,
    team_id: Optional[int] = None,
    role: str = "participant",
) -> DrillParticipant:
    """Add a participant to a drill."""
    # Check if already a participant
    existing = await db.execute(
        select(DrillParticipant).where(
            DrillParticipant.drill_id == drill_id,
            DrillParticipant.user_id == user_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("User is already a participant in this drill")
    
    participant = DrillParticipant(
        drill_id=drill_id,
        user_id=user_id,
        team_id=team_id,
        role=role,
        status="registered",
    )
    db.add(participant)
    await db.commit()
    await db.refresh(participant)
    return participant


async def remove_participant(db: AsyncSession, drill_id: int, user_id: int) -> bool:
    """Remove a participant from a drill."""
    result = await db.execute(
        delete(DrillParticipant).where(
            DrillParticipant.drill_id == drill_id,
            DrillParticipant.user_id == user_id
        )
    )
    await db.commit()
    return result.rowcount > 0


# ============================================================================
# Teams
# ============================================================================

async def list_drill_teams(db: AsyncSession, drill_id: int) -> list[DrillTeam]:
    """List all teams in a drill."""
    result = await db.execute(
        select(DrillTeam)
        .where(DrillTeam.drill_id == drill_id)
        .order_by(DrillTeam.registered_at)
    )
    return result.scalars().all()


async def add_team(
    db: AsyncSession,
    drill_id: int,
    team_id: int,
    team_side: Optional[str] = None,
) -> DrillTeam:
    """Add a team to a drill."""
    # Check if already added
    existing = await db.execute(
        select(DrillTeam).where(
            DrillTeam.drill_id == drill_id,
            DrillTeam.team_id == team_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Team is already in this drill")
    
    drill_team = DrillTeam(
        drill_id=drill_id,
        team_id=team_id,
        team_side=team_side,
    )
    db.add(drill_team)
    await db.commit()
    await db.refresh(drill_team)
    return drill_team


async def remove_team(db: AsyncSession, drill_id: int, team_id: int) -> bool:
    """Remove a team from a drill."""
    result = await db.execute(
        delete(DrillTeam).where(
            DrillTeam.drill_id == drill_id,
            DrillTeam.team_id == team_id
        )
    )
    await db.commit()
    return result.rowcount > 0


# ============================================================================
# Announcements
# ============================================================================

async def list_drill_announcements(db: AsyncSession, drill_id: int) -> list[DrillAnnouncement]:
    """List all announcements for a drill."""
    result = await db.execute(
        select(DrillAnnouncement)
        .where(DrillAnnouncement.drill_id == drill_id)
        .order_by(DrillAnnouncement.published_at.desc())
    )
    return result.scalars().all()


async def create_announcement(
    db: AsyncSession,
    drill_id: int,
    title: str,
    content: str,
    priority: str = "normal",
    published_by: Optional[int] = None,
) -> DrillAnnouncement:
    """Create a drill announcement."""
    # Validate and sanitize input
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    if not content or not content.strip():
        raise ValueError("Content cannot be empty")
    if len(title) > 255:
        raise ValueError("Title cannot exceed 255 characters")
    
    # Sanitize to prevent XSS
    title = _sanitize_text(title)
    content = _sanitize_text(content)
    
    announcement = DrillAnnouncement(
        drill_id=drill_id,
        title=title,
        content=content,
        priority=priority,
        published_by=published_by,
    )
    db.add(announcement)
    await db.commit()
    await db.refresh(announcement)
    return announcement


async def delete_announcement(db: AsyncSession, announcement_id: int) -> bool:
    """Delete an announcement by ID."""
    result = await db.execute(
        select(DrillAnnouncement).where(DrillAnnouncement.id == announcement_id)
    )
    announcement = result.scalar_one_or_none()
    if not announcement:
        return False
    await db.delete(announcement)
    await db.commit()
    return True


# ============================================================================
# Drill Objectives
# ============================================================================

async def list_drill_objectives(db: AsyncSession, drill_id: int) -> list[DrillObjective]:
    """List all objectives for a drill."""
    result = await db.execute(
        select(DrillObjective)
        .where(DrillObjective.drill_id == drill_id)
        .order_by(DrillObjective.sort_order)
    )
    return result.scalars().all()


async def create_drill_objective(
    db: AsyncSession,
    drill_id: int,
    title: str,
    description: Optional[str] = None,
    points: int = 0,
    side: Optional[str] = None,
    sort_order: int = 0,
) -> DrillObjective:
    """Create a drill objective."""
    # Validate input
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    if len(title) > 255:
        raise ValueError("Title cannot exceed 255 characters")
    if points < 0:
        raise ValueError("Points cannot be negative")
    
    # Sanitize text fields to prevent XSS
    title = _sanitize_text(title)
    description = _sanitize_text(description) if description else description
    
    objective = DrillObjective(
        drill_id=drill_id,
        title=title,
        description=description,
        points=points,
        side=side,
        sort_order=sort_order,
    )
    db.add(objective)
    await db.commit()
    await db.refresh(objective)
    return objective


# ============================================================================
# Drill Scenarios
# ============================================================================

async def list_drill_scenarios(db: AsyncSession, drill_id: int) -> list[DrillScenario]:
    """List all scenarios linked to a drill."""
    result = await db.execute(
        select(DrillScenario)
        .where(DrillScenario.drill_id == drill_id)
        .order_by(DrillScenario.created_at)
    )
    return result.scalars().all()


async def link_scenario(
    db: AsyncSession,
    drill_id: int,
    lab_id: int,
    scenario_config: Optional[dict] = None,
) -> DrillScenario:
    """Link a lab scenario to a drill."""
    # Check if already linked
    existing = await db.execute(
        select(DrillScenario).where(
            DrillScenario.drill_id == drill_id,
            DrillScenario.lab_id == lab_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Lab is already linked to this drill")
    
    scenario = DrillScenario(
        drill_id=drill_id,
        lab_id=lab_id,
        scenario_config=scenario_config or {},
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return scenario
