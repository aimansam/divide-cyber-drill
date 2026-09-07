"""Learning paths router for OxBlood v2.

Provides endpoints for learning path management, module organization, lab assignments, and progress tracking.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models_oxblood import LabDifficulty, LearningPathStatus
from app.services.learning_path_service import (
    list_learning_paths, get_learning_path, create_learning_path,
    update_learning_path, delete_learning_path,
    list_modules, get_module, create_module, update_module, delete_module,
    list_module_labs, assign_lab_to_module, remove_lab_from_module,
    get_user_progress, update_progress, get_path_completion_stats,
    list_lab_skills, add_lab_skill, remove_lab_skill,
)

router = APIRouter(prefix="/api/v2/learning-paths", tags=["Learning Paths v2"])


# ============================================================================
# Pydantic Models
# ============================================================================

class LearningPathCreate(BaseModel):
    name: str
    title: str
    description: str
    difficulty: LabDifficulty = LabDifficulty.BEGINNER
    estimated_duration_hours: Optional[int] = None
    is_public: bool = True


class LearningPathUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    difficulty: Optional[LabDifficulty] = None
    estimated_duration_hours: Optional[int] = None
    is_public: Optional[bool] = None


class ModuleCreate(BaseModel):
    title: str
    description: Optional[str] = None
    sort_order: int = 0


class ModuleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class LabAssignment(BaseModel):
    lab_id: int
    is_required: bool = True
    min_score: Optional[int] = None
    sort_order: int = 0


class ProgressUpdate(BaseModel):
    module_id: int
    lab_id: int
    status: LearningPathStatus = LearningPathStatus.IN_PROGRESS
    score: Optional[int] = None


class SkillCreate(BaseModel):
    skill_name: str
    skill_category: str
    proficiency_level: str = "intermediate"


# ============================================================================
# Helper
# ============================================================================

def path_to_dict(path) -> dict:
    """Convert learning path to dict."""
    return {
        "id": path.id,
        "name": path.name,
        "title": path.title,
        "description": path.description,
        "difficulty": path.difficulty.value if hasattr(path.difficulty, "value") else path.difficulty,
        "estimated_duration_hours": path.estimated_duration_hours,
        "is_public": path.is_public,
        "created_by": path.created_by,
        "created_at": path.created_at.isoformat() if path.created_at else None,
        "updated_at": path.updated_at.isoformat() if path.updated_at else None,
    }


def module_to_dict(module) -> dict:
    """Convert module to dict."""
    return {
        "id": module.id,
        "learning_path_id": module.learning_path_id,
        "title": module.title,
        "description": module.description,
        "sort_order": module.sort_order,
        "created_at": module.created_at.isoformat() if module.created_at else None,
    }


# ============================================================================
# Learning Path CRUD
# ============================================================================

@router.get("")
async def get_learning_paths(
    difficulty: Optional[LabDifficulty] = Query(None),
    is_public: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List learning paths with optional filters."""
    paths = await list_learning_paths(
        session, difficulty=difficulty, is_public=is_public, skip=skip, limit=limit
    )
    return {"learning_paths": [path_to_dict(path) for path in paths]}


@router.post("")
async def post_learning_path(
    data: LearningPathCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new learning path."""
    path = await create_learning_path(session, **data.model_dump())
    return {"message": "Learning path created", "path_id": path.id}


@router.get("/{path_id}")
async def get_learning_path_endpoint(
    path_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get learning path details."""
    path = await get_learning_path(session, path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    return path_to_dict(path)


@router.put("/{path_id}")
async def put_learning_path(
    path_id: int,
    data: LearningPathUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a learning path."""
    path = await update_learning_path(session, path_id, **data.model_dump(exclude_none=True))
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    return {"message": "Learning path updated"}


@router.delete("/{path_id}")
async def delete_learning_path_endpoint(
    path_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a learning path (soft delete)."""
    deleted = await delete_learning_path(session, path_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learning path not found")
    return {"message": "Learning path deleted"}


# ============================================================================
# Module Management
# ============================================================================

@router.get("/{path_id}/modules")
async def get_modules(
    path_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get all modules in a learning path."""
    path = await get_learning_path(session, path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    modules = await list_modules(session, path_id)
    return {"modules": [module_to_dict(module) for module in modules]}


@router.post("/{path_id}/modules")
async def post_module(
    path_id: int,
    data: ModuleCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new module in a learning path."""
    path = await get_learning_path(session, path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    module = await create_module(session, path_id, **data.model_dump())
    return {"message": "Module created", "module_id": module.id}


@router.put("/{path_id}/modules/{module_id}")
async def put_module(
    path_id: int,
    module_id: int,
    data: ModuleUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a module."""
    module = await update_module(session, module_id, **data.model_dump(exclude_none=True))
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return {"message": "Module updated"}


@router.delete("/{path_id}/modules/{module_id}")
async def delete_module_endpoint(
    path_id: int,
    module_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a module and its lab assignments."""
    deleted = await delete_module(session, module_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Module not found")
    return {"message": "Module deleted"}


# ============================================================================
# Lab Assignments
# ============================================================================

@router.get("/{path_id}/modules/{module_id}/labs")
async def get_module_labs(
    path_id: int,
    module_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get all labs assigned to a module."""
    module = await get_module(session, module_id)
    if not module or module.learning_path_id != path_id:
        raise HTTPException(status_code=404, detail="Module not found")
    labs = await list_module_labs(session, module_id)
    return {
        "labs": [
            {
                "id": lab.id,
                "lab_id": lab.lab_id,
                "is_required": lab.is_required,
                "min_score": lab.min_score,
                "sort_order": lab.sort_order,
            }
            for lab in labs
        ]
    }


@router.post("/{path_id}/modules/{module_id}/labs")
async def post_module_lab(
    path_id: int,
    module_id: int,
    data: LabAssignment,
    session: AsyncSession = Depends(get_session),
):
    """Assign a lab to a module."""
    module = await get_module(session, module_id)
    if not module or module.learning_path_id != path_id:
        raise HTTPException(status_code=404, detail="Module not found")
    try:
        assignment = await assign_lab_to_module(
            session, module_id, data.lab_id, data.is_required, data.min_score, data.sort_order
        )
        return {"message": "Lab assigned to module", "assignment_id": assignment.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{path_id}/modules/{module_id}/labs/{lab_id}")
async def delete_module_lab(
    path_id: int,
    module_id: int,
    lab_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Remove a lab assignment from a module."""
    module = await get_module(session, module_id)
    if not module or module.learning_path_id != path_id:
        raise HTTPException(status_code=404, detail="Module not found")
    removed = await remove_lab_from_module(session, module_id, lab_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Lab assignment not found")
    return {"message": "Lab removed from module"}


# ============================================================================
# Progress Tracking
# ============================================================================

@router.get("/{path_id}/progress")
async def get_progress(
    path_id: int,
    user_id: int = Query(..., description="User ID"),
    session: AsyncSession = Depends(get_session),
):
    """Get user's progress in a learning path."""
    path = await get_learning_path(session, path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    progress = await get_user_progress(session, path_id, user_id)
    stats = await get_path_completion_stats(session, path_id, user_id)
    return {
        "progress": [
            {
                "id": p.id,
                "module_id": p.module_id,
                "lab_id": p.lab_id,
                "status": p.status.value if hasattr(p.status, "value") else p.status,
                "score": p.score,
                "started_at": p.started_at.isoformat() if p.started_at else None,
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in progress
        ],
        "stats": stats,
    }


@router.post("/{path_id}/progress")
async def post_progress(
    path_id: int,
    data: ProgressUpdate,
    user_id: int = Query(..., description="User ID"),
    session: AsyncSession = Depends(get_session),
):
    """Update user's progress for a lab."""
    path = await get_learning_path(session, path_id)
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    progress = await update_progress(
        session, path_id, data.module_id, data.lab_id, user_id, data.status, data.score
    )
    return {
        "message": "Progress updated",
        "progress_id": progress.id,
        "status": progress.status.value if hasattr(progress.status, "value") else progress.status,
    }


# ============================================================================
# Lab Skills
# ============================================================================

@router.get("/labs/{lab_id}/skills")
async def get_lab_skills(
    lab_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get all skills taught by a lab."""
    skills = await list_lab_skills(session, lab_id)
    return {
        "skills": [
            {
                "id": s.id,
                "skill_name": s.skill_name,
                "skill_category": s.skill_category,
                "proficiency_level": s.proficiency_level,
            }
            for s in skills
        ]
    }


@router.post("/labs/{lab_id}/skills")
async def post_lab_skill(
    lab_id: int,
    data: SkillCreate,
    session: AsyncSession = Depends(get_session),
):
    """Add a skill to a lab."""
    try:
        skill = await add_lab_skill(
            session, lab_id, data.skill_name, data.skill_category, data.proficiency_level
        )
        return {"message": "Skill added", "skill_id": skill.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/labs/{lab_id}/skills/{skill_name}")
async def delete_lab_skill(
    lab_id: int,
    skill_name: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a skill from a lab."""
    removed = await remove_lab_skill(session, lab_id, skill_name)
    if not removed:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"message": "Skill removed"}
