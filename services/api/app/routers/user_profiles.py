"""User profiles router for OxBlood.

Provides endpoints for user profile management, badges, and activity tracking.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models import User
from app.core.auth import current_token
from sqlalchemy import select
from app.services.user_profile_service import (
    get_user_profile,
    create_user_profile,
    update_user_profile,
    get_user_badges,
    award_badge,
    log_user_activity,
    get_user_activity,
    get_all_badges,
    get_badge,
)

router = APIRouter(prefix="/api/v2/users", tags=["User Profiles v2"])


# ============================================================================
# Pydantic Models
# ============================================================================

class UserProfileCreate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    organization: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    github_username: Optional[str] = None
    linkedin_url: Optional[str] = None
    skills: Optional[list[str]] = None
    interests: Optional[list[str]] = None
    preferences: Optional[dict] = None


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    organization: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    github_username: Optional[str] = None
    linkedin_url: Optional[str] = None
    skills: Optional[list[str]] = None
    interests: Optional[list[str]] = None
    preferences: Optional[dict] = None


class BadgeAward(BaseModel):
    badge_id: int


# ============================================================================
# User Profile Endpoints
# ============================================================================

@router.get("/me")
async def get_current_user(
    db: AsyncSession = Depends(get_session),
    token=Depends(current_token),
):
    """Get current user's database ID based on JWT token."""
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    stmt = select(User).where(User.sub == token.sub)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "sub": user.sub,
        "role": user.role,
    }


@router.get("/{user_id}/profile")
async def get_profile(
    user_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get user profile."""
    profile = await get_user_profile(db, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "full_name": profile.full_name,
        "bio": profile.bio,
        "avatar_url": profile.avatar_url,
        "organization": profile.organization,
        "location": profile.location,
        "website": profile.website,
        "github_username": profile.github_username,
        "linkedin_url": profile.linkedin_url,
        "skills": profile.skills,
        "interests": profile.interests,
        "preferences": profile.preferences,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


@router.post("/{user_id}/profile")
async def create_profile(
    user_id: int,
    profile_data: UserProfileCreate,
    db: AsyncSession = Depends(get_session),
):
    """Create user profile."""
    # Check if profile already exists
    existing = await get_user_profile(db, user_id)
    if existing:
        raise HTTPException(status_code=400, detail="Profile already exists")
    
    profile = await create_user_profile(
        db,
        user_id=user_id,
        **profile_data.model_dump(exclude_none=True),
    )
    
    # Log activity
    await log_user_activity(
        db,
        user_id=user_id,
        action="profile.created",
        resource_type="user_profile",
        resource_id=profile.id,
    )
    
    return {"message": "Profile created", "profile_id": profile.id}


@router.put("/{user_id}/profile")
async def update_profile(
    user_id: int,
    profile_data: UserProfileUpdate,
    db: AsyncSession = Depends(get_session),
):
    """Update user profile."""
    profile = await update_user_profile(
        db,
        user_id=user_id,
        **profile_data.model_dump(exclude_none=True),
    )
    
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Log activity
    await log_user_activity(
        db,
        user_id=user_id,
        action="profile.updated",
        resource_type="user_profile",
        resource_id=profile.id,
    )
    
    return {"message": "Profile updated"}


# ============================================================================
# Badge Endpoints
# ============================================================================

@router.get("/badges")
async def list_all_badges(
    db: AsyncSession = Depends(get_session),
):
    """Get all available badges."""
    badges = await get_all_badges(db)
    return {
        "badges": [
            {
                "id": b.id,
                "name": b.name,
                "description": b.description,
                "icon": b.icon,
                "category": b.category,
                "rarity": b.rarity,
                "criteria": b.criteria,
            }
            for b in badges
        ]
    }


@router.get("/{user_id}/badges")
async def get_badges(
    user_id: int,
    db: AsyncSession = Depends(get_session),
):
    """Get all badges earned by user."""
    user_badges = await get_user_badges(db, user_id)
    return {
        "badges": [
            {
                "id": ub.id,
                "badge_id": ub.badge_id,
                "earned_at": ub.earned_at.isoformat(),
            }
            for ub in user_badges
        ]
    }


@router.post("/{user_id}/badges")
async def award_badge_endpoint(
    user_id: int,
    badge_data: BadgeAward,
    db: AsyncSession = Depends(get_session),
):
    """Award a badge to user."""
    # Check if badge exists
    badge = await get_badge(db, badge_data.badge_id)
    if not badge:
        raise HTTPException(status_code=404, detail="Badge not found")
    
    try:
        user_badge = await award_badge(db, user_id, badge_data.badge_id)
        
        # Log activity
        await log_user_activity(
            db,
            user_id=user_id,
            action="badge.earned",
            resource_type="badge",
            resource_id=badge.id,
            details={"badge_name": badge.name},
        )
        
        return {
            "message": "Badge awarded",
            "badge": {
                "id": user_badge.id,
                "badge_id": badge.id,
                "name": badge.name,
                "earned_at": user_badge.earned_at.isoformat(),
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Activity Endpoints
# ============================================================================

@router.get("/{user_id}/activity")
async def get_activity(
    user_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
):
    """Get recent user activity."""
    activity = await get_user_activity(db, user_id, limit=limit)
    return {
        "activity": [
            {
                "id": log.id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in activity
        ]
    }
