"""Learning path service for OxBlood v2.

Handles learning path CRUD, module management, lab assignments, and progress tracking.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_oxblood import (
    LearningPath, LearningPathModule, LearningPathLab,
    UserLearningProgress, LabSkill, Lab,
    LearningPathStatus, LabDifficulty,
)


# ============================================================================
# Learning Path CRUD
# ============================================================================

async def list_learning_paths(
    db: AsyncSession,
    difficulty: Optional[LabDifficulty] = None,
    is_public: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[LearningPath]:
    """List learning paths with optional filters."""
    query = select(LearningPath).where(LearningPath.deleted_at.is_(None))
    if difficulty:
        query = query.where(LearningPath.difficulty == difficulty)
    if is_public is not None:
        query = query.where(LearningPath.is_public == is_public)
    query = query.order_by(LearningPath.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_learning_path(db: AsyncSession, path_id: int) -> Optional[LearningPath]:
    """Get a learning path by ID."""
    result = await db.execute(
        select(LearningPath).where(
            LearningPath.id == path_id,
            LearningPath.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def create_learning_path(
    db: AsyncSession,
    name: str,
    title: str,
    description: str,
    difficulty: LabDifficulty = LabDifficulty.BEGINNER,
    estimated_duration_hours: Optional[int] = None,
    is_public: bool = True,
    created_by: Optional[int] = None,
) -> LearningPath:
    """Create a new learning path."""
    path = LearningPath(
        name=name,
        title=title,
        description=description,
        difficulty=difficulty,
        estimated_duration_hours=estimated_duration_hours,
        is_public=is_public,
        created_by=created_by,
    )
    db.add(path)
    await db.commit()
    await db.refresh(path)
    return path


async def update_learning_path(
    db: AsyncSession,
    path_id: int,
    **kwargs
) -> Optional[LearningPath]:
    """Update a learning path."""
    path = await get_learning_path(db, path_id)
    if not path:
        return None
    for key, value in kwargs.items():
        if hasattr(path, key) and value is not None:
            setattr(path, key, value)
    await db.commit()
    await db.refresh(path)
    return path


async def delete_learning_path(db: AsyncSession, path_id: int) -> bool:
    """Soft delete a learning path."""
    from datetime import datetime, timezone
    path = await get_learning_path(db, path_id)
    if not path:
        return False
    path.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ============================================================================
# Module Management
# ============================================================================

async def list_modules(db: AsyncSession, path_id: int) -> list[LearningPathModule]:
    """List all modules in a learning path."""
    result = await db.execute(
        select(LearningPathModule)
        .where(LearningPathModule.learning_path_id == path_id)
        .order_by(LearningPathModule.sort_order)
    )
    return result.scalars().all()


async def get_module(db: AsyncSession, module_id: int) -> Optional[LearningPathModule]:
    """Get a module by ID."""
    result = await db.execute(
        select(LearningPathModule).where(LearningPathModule.id == module_id)
    )
    return result.scalar_one_or_none()


async def create_module(
    db: AsyncSession,
    path_id: int,
    title: str,
    description: Optional[str] = None,
    sort_order: int = 0,
) -> LearningPathModule:
    """Create a new module in a learning path."""
    module = LearningPathModule(
        learning_path_id=path_id,
        title=title,
        description=description,
        sort_order=sort_order,
    )
    db.add(module)
    await db.commit()
    await db.refresh(module)
    return module


async def update_module(
    db: AsyncSession,
    module_id: int,
    **kwargs
) -> Optional[LearningPathModule]:
    """Update a module."""
    module = await get_module(db, module_id)
    if not module:
        return None
    for key, value in kwargs.items():
        if hasattr(module, key) and value is not None:
            setattr(module, key, value)
    await db.commit()
    await db.refresh(module)
    return module


async def delete_module(db: AsyncSession, module_id: int) -> bool:
    """Delete a module and its lab assignments."""
    module = await get_module(db, module_id)
    if not module:
        return False
    # Delete associated lab assignments
    await db.execute(
        delete(LearningPathLab).where(LearningPathLab.module_id == module_id)
    )
    await db.delete(module)
    await db.commit()
    return True


# ============================================================================
# Lab Assignments
# ============================================================================

async def list_module_labs(db: AsyncSession, module_id: int) -> list[LearningPathLab]:
    """List all labs assigned to a module."""
    result = await db.execute(
        select(LearningPathLab)
        .where(LearningPathLab.module_id == module_id)
        .order_by(LearningPathLab.sort_order)
    )
    return result.scalars().all()


async def assign_lab_to_module(
    db: AsyncSession,
    module_id: int,
    lab_id: int,
    is_required: bool = True,
    min_score: Optional[int] = None,
    sort_order: int = 0,
) -> LearningPathLab:
    """Assign a lab to a module."""
    # Check if already assigned
    existing = await db.execute(
        select(LearningPathLab).where(
            LearningPathLab.module_id == module_id,
            LearningPathLab.lab_id == lab_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Lab is already assigned to this module")
    
    assignment = LearningPathLab(
        module_id=module_id,
        lab_id=lab_id,
        is_required=is_required,
        min_score=min_score,
        sort_order=sort_order,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def remove_lab_from_module(db: AsyncSession, module_id: int, lab_id: int) -> bool:
    """Remove a lab assignment from a module."""
    result = await db.execute(
        delete(LearningPathLab).where(
            LearningPathLab.module_id == module_id,
            LearningPathLab.lab_id == lab_id
        )
    )
    await db.commit()
    return result.rowcount > 0


# ============================================================================
# Progress Tracking
# ============================================================================

async def get_user_progress(
    db: AsyncSession,
    path_id: int,
    user_id: int,
) -> list[UserLearningProgress]:
    """Get user's progress in a learning path."""
    result = await db.execute(
        select(UserLearningProgress)
        .where(
            UserLearningProgress.learning_path_id == path_id,
            UserLearningProgress.user_id == user_id
        )
        .order_by(UserLearningProgress.started_at)
    )
    return result.scalars().all()


async def update_progress(
    db: AsyncSession,
    path_id: int,
    module_id: int,
    lab_id: int,
    user_id: int,
    status: LearningPathStatus = LearningPathStatus.IN_PROGRESS,
    score: Optional[int] = None,
) -> UserLearningProgress:
    """Update user's progress for a lab."""
    # Check if progress record exists
    existing = await db.execute(
        select(UserLearningProgress).where(
            UserLearningProgress.learning_path_id == path_id,
            UserLearningProgress.module_id == module_id,
            UserLearningProgress.lab_id == lab_id,
            UserLearningProgress.user_id == user_id
        )
    )
    progress = existing.scalar_one_or_none()
    
    if progress:
        # Update existing progress
        progress.status = status
        if score is not None:
            progress.score = score
        if status == LearningPathStatus.COMPLETED:
            from datetime import datetime, timezone
            progress.completed_at = datetime.now(timezone.utc)
    else:
        # Create new progress record
        progress = UserLearningProgress(
            learning_path_id=path_id,
            module_id=module_id,
            lab_id=lab_id,
            user_id=user_id,
            status=status,
            score=score,
        )
        if status == LearningPathStatus.COMPLETED:
            from datetime import datetime, timezone
            progress.completed_at = datetime.now(timezone.utc)
        db.add(progress)
    
    await db.commit()
    await db.refresh(progress)
    return progress


async def get_path_completion_stats(
    db: AsyncSession,
    path_id: int,
    user_id: int,
) -> dict:
    """Get completion statistics for a user in a learning path."""
    # Get all labs in the path
    modules = await list_modules(db, path_id)
    total_labs = 0
    for module in modules:
        labs = await list_module_labs(db, module.id)
        total_labs += len(labs)
    
    # Get user's progress
    progress_records = await get_user_progress(db, path_id, user_id)
    completed_labs = sum(
        1 for p in progress_records
        if p.status == LearningPathStatus.COMPLETED
    )
    in_progress_labs = sum(
        1 for p in progress_records
        if p.status == LearningPathStatus.IN_PROGRESS
    )
    
    completion_percentage = (completed_labs / total_labs * 100) if total_labs > 0 else 0
    
    return {
        "total_labs": total_labs,
        "completed_labs": completed_labs,
        "in_progress_labs": in_progress_labs,
        "completion_percentage": round(completion_percentage, 2),
    }


# ============================================================================
# Lab Skills
# ============================================================================

async def list_lab_skills(db: AsyncSession, lab_id: int) -> list[LabSkill]:
    """List all skills taught by a lab."""
    result = await db.execute(
        select(LabSkill).where(LabSkill.lab_id == lab_id)
    )
    return result.scalars().all()


async def add_lab_skill(
    db: AsyncSession,
    lab_id: int,
    skill_name: str,
    skill_category: str,
    proficiency_level: str = "intermediate",
) -> LabSkill:
    """Add a skill to a lab."""
    # Check if already exists
    existing = await db.execute(
        select(LabSkill).where(
            LabSkill.lab_id == lab_id,
            LabSkill.skill_name == skill_name
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Skill already exists for this lab")
    
    skill = LabSkill(
        lab_id=lab_id,
        skill_name=skill_name,
        skill_category=skill_category,
        proficiency_level=proficiency_level,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


async def remove_lab_skill(db: AsyncSession, lab_id: int, skill_name: str) -> bool:
    """Remove a skill from a lab."""
    result = await db.execute(
        delete(LabSkill).where(
            LabSkill.lab_id == lab_id,
            LabSkill.skill_name == skill_name
        )
    )
    await db.commit()
    return result.rowcount > 0
