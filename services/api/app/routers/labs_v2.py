"""Labs v2 router for OxBlood.

Provides endpoints for lab management with the new schema.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models_oxblood import LabStatus, LabDifficulty
from app.services.lab_service import (
    list_labs, get_lab, create_lab, update_lab, publish_lab, archive_lab,
    list_categories, create_category,
    list_lab_flags, create_lab_flag,
    list_lab_objectives, create_lab_objective,
    list_lab_hints, create_lab_hint,
    list_all_tags, create_tag, add_tag_to_lab, remove_tag_from_lab, get_lab_tags,
)

router = APIRouter(prefix="/api/v2/labs", tags=["Labs v2"])


# ============================================================================
# Pydantic Models
# ============================================================================

class LabCreate(BaseModel):
    name: str
    title: str
    description: str
    difficulty: LabDifficulty = LabDifficulty.BEGINNER
    duration_minutes: Optional[int] = None
    category_id: Optional[int] = None
    is_public: bool = False
    requires_team: bool = False
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    spec: Optional[dict] = None
    authors: Optional[list[str]] = None
    prerequisites: Optional[list] = None
    learning_objectives: Optional[list[str]] = None


class LabUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    difficulty: Optional[LabDifficulty] = None
    duration_minutes: Optional[int] = None
    category_id: Optional[int] = None
    is_public: Optional[bool] = None
    requires_team: Optional[bool] = None
    min_team_size: Optional[int] = None
    max_team_size: Optional[int] = None
    spec: Optional[dict] = None
    authors: Optional[list[str]] = None
    prerequisites: Optional[list] = None
    learning_objectives: Optional[list[str]] = None


class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int = 0


class FlagCreate(BaseModel):
    flag_id: str
    name: str
    value: str
    points: int = 100
    description: Optional[str] = None
    category: Optional[str] = None
    hint: Optional[str] = None
    hint_penalty: int = 10
    decay_window_seconds: int = 1800
    sort_order: int = 0


class ObjectiveCreate(BaseModel):
    title: str
    description: Optional[str] = None
    points: int = 0
    is_required: bool = True
    sort_order: int = 0


class HintCreate(BaseModel):
    title: str
    content: str
    objective_id: Optional[int] = None
    penalty_points: int = 5
    sort_order: int = 0


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


# ============================================================================
# Helper
# ============================================================================

def lab_to_dict(lab: "Lab") -> dict:
    """Convert lab to dict (avoid circular import)."""
    return {
        "id": lab.id,
        "name": lab.name,
        "title": lab.title,
        "description": lab.description,
        "version": lab.version,
        "category_id": lab.category_id,
        "difficulty": lab.difficulty.value if hasattr(lab.difficulty, "value") else lab.difficulty,
        "duration_minutes": lab.duration_minutes,
        "status": lab.status.value if hasattr(lab.status, "value") else lab.status,
        "is_public": lab.is_public,
        "requires_team": lab.requires_team,
        "min_team_size": lab.min_team_size,
        "max_team_size": lab.max_team_size,
        "spec": lab.spec,
        "authors": lab.authors,
        "prerequisites": lab.prerequisites,
        "learning_objectives": lab.learning_objectives,
        "created_by": lab.created_by,
        "created_at": lab.created_at.isoformat() if lab.created_at else None,
        "updated_at": lab.updated_at.isoformat() if lab.updated_at else None,
        "published_at": lab.published_at.isoformat() if lab.published_at else None,
        "archived_at": lab.archived_at.isoformat() if lab.archived_at else None,
    }


# ============================================================================
# Static routes (MUST come before /{lab_id})
# ============================================================================

@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_session)):
    """List all lab categories."""
    categories = await list_categories(db)
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "icon": c.icon,
                "parent_id": c.parent_id,
                "sort_order": c.sort_order,
            }
            for c in categories
        ]
    }


@router.post("/categories")
async def post_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new lab category."""
    category = await create_category(db, **data.model_dump())
    return {"message": "Category created", "category_id": category.id}


@router.get("/tags")
async def get_all_tags(db: AsyncSession = Depends(get_session)):
    """List all tags."""
    tags = await list_all_tags(db)
    return {
        "tags": [
            {"id": t.id, "name": t.name, "color": t.color}
            for t in tags
        ]
    }


@router.post("/tags")
async def post_tag(
    data: TagCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new tag."""
    tag = await create_tag(db, **data.model_dump())
    return {"message": "Tag created", "tag_id": tag.id}


# ============================================================================
# Lab CRUD
# ============================================================================

@router.get("")
async def get_labs(
    status: Optional[LabStatus] = Query(None),
    difficulty: Optional[LabDifficulty] = Query(None),
    category_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """List labs with optional filters."""
    labs = await list_labs(
        db,
        status=status,
        difficulty=difficulty,
        category_id=category_id,
        skip=skip,
        limit=limit,
    )
    return {"labs": [lab_to_dict(lab) for lab in labs]}


@router.post("")
async def post_lab(
    data: LabCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new lab."""
    # Check for duplicate name
    existing = await get_lab_by_name(db, data.name)
    if existing:
        raise HTTPException(status_code=400, detail="Lab with this name already exists")
    
    lab = await create_lab(db, **data.model_dump())
    return {"message": "Lab created", "lab_id": lab.id}


async def get_lab_by_name(db: AsyncSession, name: str):
    """Helper to check if lab name exists."""
    from sqlalchemy import select
    from app.db.models_oxblood import Lab
    result = await db.execute(
        select(Lab).where(Lab.name == name, Lab.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


@router.get("/{lab_id}")
async def get_lab_endpoint(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get lab details."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    return lab_to_dict(lab)


@router.put("/{lab_id}")
async def put_lab(
    lab_id: int,
    data: LabUpdate,
    db: AsyncSession = Depends(get_session),
):
    """Update a lab."""
    lab = await update_lab(db, lab_id, **data.model_dump(exclude_none=True))
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    return {"message": "Lab updated"}


@router.delete("/{lab_id}")
async def delete_lab(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Archive a lab (soft delete)."""
    lab = await archive_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    return {"message": "Lab archived"}


@router.post("/{lab_id}/publish")
async def publish_lab_endpoint(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Publish a lab."""
    lab = await publish_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    return {"message": "Lab published"}


# ============================================================================
# Flags
# ============================================================================

@router.get("/{lab_id}/flags")
async def get_lab_flags(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all flags for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    flags = await list_lab_flags(db, lab_id)
    return {
        "flags": [
            {
                "id": f.id,
                "flag_id": f.flag_id,
                "name": f.name,
                "description": f.description,
                "points": f.points,
                "category": f.category,
                "hint": f.hint,
                "hint_penalty": f.hint_penalty,
                "decay_window_seconds": f.decay_window_seconds,
                "sort_order": f.sort_order,
            }
            for f in flags
        ]
    }


@router.post("/{lab_id}/flags")
async def post_lab_flag(
    lab_id: int,
    data: FlagCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new flag for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    flag = await create_lab_flag(db, lab_id=lab_id, **data.model_dump())
    return {"message": "Flag created", "flag_db_id": flag.id}


# ============================================================================
# Objectives
# ============================================================================

@router.get("/{lab_id}/objectives")
async def get_lab_objectives(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all objectives for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    objectives = await list_lab_objectives(db, lab_id)
    return {
        "objectives": [
            {
                "id": o.id,
                "title": o.title,
                "description": o.description,
                "points": o.points,
                "is_required": o.is_required,
                "sort_order": o.sort_order,
            }
            for o in objectives
        ]
    }


@router.post("/{lab_id}/objectives")
async def post_lab_objective(
    lab_id: int,
    data: ObjectiveCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new objective for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    objective = await create_lab_objective(db, lab_id=lab_id, **data.model_dump())
    return {"message": "Objective created", "objective_id": objective.id}


# ============================================================================
# Hints
# ============================================================================

@router.get("/{lab_id}/hints")
async def get_lab_hints(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all hints for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    hints = await list_lab_hints(db, lab_id)
    return {
        "hints": [
            {
                "id": h.id,
                "title": h.title,
                "content": h.content,
                "objective_id": h.objective_id,
                "penalty_points": h.penalty_points,
                "sort_order": h.sort_order,
            }
            for h in hints
        ]
    }


@router.post("/{lab_id}/hints")
async def post_lab_hint(
    lab_id: int,
    data: HintCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create a new hint for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    hint = await create_lab_hint(db, lab_id=lab_id, **data.model_dump())
    return {"message": "Hint created", "hint_id": hint.id}


# ============================================================================
# Tags (per lab)
# ============================================================================

@router.get("/{lab_id}/tags")
async def get_lab_tags_endpoint(
    lab_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all tags for a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    tags = await get_lab_tags(db, lab_id)
    return {
        "tags": [
            {"id": t.id, "name": t.name, "color": t.color}
            for t in tags
        ]
    }


@router.post("/{lab_id}/tags/{tag_id}")
async def add_tag_to_lab_endpoint(
    lab_id: int,
    tag_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Add a tag to a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    await add_tag_to_lab(db, lab_id, tag_id)
    return {"message": "Tag added to lab"}


@router.delete("/{lab_id}/tags/{tag_id}")
async def remove_tag_from_lab_endpoint(
    lab_id: int,
    tag_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Remove a tag from a lab."""
    lab = await get_lab(db, lab_id)
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    removed = await remove_tag_from_lab(db, lab_id, tag_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Tag not found on lab")
    return {"message": "Tag removed from lab"}
