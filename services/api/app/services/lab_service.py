"""Lab service for OxBlood v2.

Handles lab CRUD, categories, flags, objectives, hints, and tags.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models_oxblood import (
    Lab, LabCategory, Tag, LabTag, LabFlag, LabObjective, LabHint, LabFile,
    LabStatus, LabDifficulty,
)


# ============================================================================
# Lab CRUD
# ============================================================================

async def list_labs(
    db: AsyncSession,
    status: Optional[LabStatus] = None,
    difficulty: Optional[LabDifficulty] = None,
    category_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Lab]:
    """List labs with optional filters."""
    query = select(Lab).where(Lab.deleted_at.is_(None))
    if status:
        query = query.where(Lab.status == status)
    if difficulty:
        query = query.where(Lab.difficulty == difficulty)
    if category_id:
        query = query.where(Lab.category_id == category_id)
    query = query.order_by(Lab.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_lab(db: AsyncSession, lab_id: int) -> Optional[Lab]:
    """Get a lab by ID."""
    result = await db.execute(
        select(Lab).where(Lab.id == lab_id, Lab.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_lab(
    db: AsyncSession,
    name: str,
    title: str,
    description: str,
    difficulty: LabDifficulty = LabDifficulty.BEGINNER,
    duration_minutes: Optional[int] = None,
    category_id: Optional[int] = None,
    is_public: bool = False,
    requires_team: bool = False,
    min_team_size: Optional[int] = None,
    max_team_size: Optional[int] = None,
    spec: Optional[dict] = None,
    authors: Optional[list] = None,
    prerequisites: Optional[list] = None,
    learning_objectives: Optional[list] = None,
    created_by: Optional[int] = None,
) -> Lab:
    """Create a new lab."""
    lab = Lab(
        name=name,
        title=title,
        description=description,
        difficulty=difficulty,
        duration_minutes=duration_minutes,
        category_id=category_id,
        status=LabStatus.DRAFT,
        is_public=is_public,
        requires_team=requires_team,
        min_team_size=min_team_size,
        max_team_size=max_team_size,
        spec=spec or {},
        authors=authors or [],
        prerequisites=prerequisites or [],
        learning_objectives=learning_objectives or [],
        created_by=created_by,
    )
    db.add(lab)
    await db.commit()
    await db.refresh(lab)
    return lab


async def update_lab(db: AsyncSession, lab_id: int, **kwargs) -> Optional[Lab]:
    """Update a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        return None
    for key, value in kwargs.items():
        if hasattr(lab, key) and value is not None:
            setattr(lab, key, value)
    await db.commit()
    await db.refresh(lab)
    return lab


async def publish_lab(db: AsyncSession, lab_id: int) -> Optional[Lab]:
    """Publish a lab (change status from draft to published)."""
    from datetime import datetime, timezone
    lab = await get_lab(db, lab_id)
    if not lab:
        return None
    lab.status = LabStatus.PUBLISHED
    lab.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lab)
    return lab


async def archive_lab(db: AsyncSession, lab_id: int) -> Optional[Lab]:
    """Archive a lab (soft delete)."""
    from datetime import datetime, timezone
    lab = await get_lab(db, lab_id)
    if not lab:
        return None
    lab.status = LabStatus.ARCHIVED
    lab.archived_at = datetime.now(timezone.utc)
    lab.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(lab)
    return lab


# ============================================================================
# Categories
# ============================================================================

async def list_categories(db: AsyncSession) -> list[LabCategory]:
    """List all lab categories."""
    result = await db.execute(
        select(LabCategory).order_by(LabCategory.sort_order, LabCategory.name)
    )
    return result.scalars().all()


async def create_category(
    db: AsyncSession,
    name: str,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    parent_id: Optional[int] = None,
    sort_order: int = 0,
) -> LabCategory:
    """Create a new lab category."""
    category = LabCategory(
        name=name,
        description=description,
        icon=icon,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


# ============================================================================
# Flags
# ============================================================================

async def list_lab_flags(db: AsyncSession, lab_id: int) -> list[LabFlag]:
    """List all flags for a lab."""
    result = await db.execute(
        select(LabFlag)
        .where(LabFlag.lab_id == lab_id)
        .order_by(LabFlag.sort_order)
    )
    return result.scalars().all()


async def create_lab_flag(
    db: AsyncSession,
    lab_id: int,
    flag_id: str,
    name: str,
    value: str,
    points: int = 100,
    description: Optional[str] = None,
    category: Optional[str] = None,
    hint: Optional[str] = None,
    hint_penalty: int = 10,
    decay_window_seconds: int = 1800,
    sort_order: int = 0,
) -> LabFlag:
    """Create a new flag for a lab."""
    flag = LabFlag(
        lab_id=lab_id,
        flag_id=flag_id,
        name=name,
        value=value,
        points=points,
        description=description,
        category=category,
        hint=hint,
        hint_penalty=hint_penalty,
        decay_window_seconds=decay_window_seconds,
        sort_order=sort_order,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)
    return flag


# ============================================================================
# Objectives
# ============================================================================

async def list_lab_objectives(db: AsyncSession, lab_id: int) -> list[LabObjective]:
    """List all objectives for a lab."""
    result = await db.execute(
        select(LabObjective)
        .where(LabObjective.lab_id == lab_id)
        .order_by(LabObjective.sort_order)
    )
    return result.scalars().all()


async def create_lab_objective(
    db: AsyncSession,
    lab_id: int,
    title: str,
    description: Optional[str] = None,
    points: int = 0,
    is_required: bool = True,
    sort_order: int = 0,
) -> LabObjective:
    """Create a new objective for a lab."""
    objective = LabObjective(
        lab_id=lab_id,
        title=title,
        description=description,
        points=points,
        is_required=is_required,
        sort_order=sort_order,
    )
    db.add(objective)
    await db.commit()
    await db.refresh(objective)
    return objective


# ============================================================================
# Hints
# ============================================================================

async def list_lab_hints(db: AsyncSession, lab_id: int) -> list[LabHint]:
    """List all hints for a lab."""
    result = await db.execute(
        select(LabHint)
        .where(LabHint.lab_id == lab_id)
        .order_by(LabHint.sort_order)
    )
    return result.scalars().all()


async def create_lab_hint(
    db: AsyncSession,
    lab_id: int,
    title: str,
    content: str,
    objective_id: Optional[int] = None,
    penalty_points: int = 5,
    sort_order: int = 0,
) -> LabHint:
    """Create a new hint for a lab."""
    hint = LabHint(
        lab_id=lab_id,
        title=title,
        content=content,
        objective_id=objective_id,
        penalty_points=penalty_points,
        sort_order=sort_order,
    )
    db.add(hint)
    await db.commit()
    await db.refresh(hint)
    return hint


# ============================================================================
# Tags
# ============================================================================

async def list_all_tags(db: AsyncSession) -> list[Tag]:
    """List all tags."""
    result = await db.execute(select(Tag).order_by(Tag.name))
    return result.scalars().all()


async def create_tag(
    db: AsyncSession,
    name: str,
    color: Optional[str] = None,
) -> Tag:
    """Create a new tag."""
    tag = Tag(name=name, color=color)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def add_tag_to_lab(db: AsyncSession, lab_id: int, tag_id: int) -> LabTag:
    """Add a tag to a lab."""
    lab_tag = LabTag(lab_id=lab_id, tag_id=tag_id)
    db.add(lab_tag)
    await db.commit()
    return lab_tag


async def remove_tag_from_lab(db: AsyncSession, lab_id: int, tag_id: int) -> bool:
    """Remove a tag from a lab."""
    result = await db.execute(
        delete(LabTag).where(LabTag.lab_id == lab_id, LabTag.tag_id == tag_id)
    )
    await db.commit()
    return result.rowcount > 0


async def get_lab_tags(db: AsyncSession, lab_id: int) -> list[Tag]:
    """Get all tags for a lab."""
    result = await db.execute(
        select(Tag)
        .join(LabTag, LabTag.tag_id == Tag.id)
        .where(LabTag.lab_id == lab_id)
    )
    return result.scalars().all()
