"""User profile service for OxBlood.

This service handles user profile operations using the new schema.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_oxblood import User, UserProfile, Badge, UserBadge, UserActivityLog


async def get_user_profile(db: AsyncSession, user_id: int) -> Optional[UserProfile]:
    """Get user profile by user ID."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_user_profile(
    db: AsyncSession,
    user_id: int,
    full_name: Optional[str] = None,
    bio: Optional[str] = None,
    avatar_url: Optional[str] = None,
    organization: Optional[str] = None,
    location: Optional[str] = None,
    website: Optional[str] = None,
    github_username: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    skills: Optional[list] = None,
    interests: Optional[list] = None,
    preferences: Optional[dict] = None,
) -> UserProfile:
    """Create a new user profile."""
    profile = UserProfile(
        user_id=user_id,
        full_name=full_name,
        bio=bio,
        avatar_url=avatar_url,
        organization=organization,
        location=location,
        website=website,
        github_username=github_username,
        linkedin_url=linkedin_url,
        skills=skills or [],
        interests=interests or [],
        preferences=preferences or {},
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_user_profile(
    db: AsyncSession,
    user_id: int,
    **kwargs,
) -> Optional[UserProfile]:
    """Update user profile."""
    profile = await get_user_profile(db, user_id)
    if not profile:
        return None
    
    for key, value in kwargs.items():
        if hasattr(profile, key) and value is not None:
            setattr(profile, key, value)
    
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_user_badges(db: AsyncSession, user_id: int) -> list[UserBadge]:
    """Get all badges earned by a user."""
    result = await db.execute(
        select(UserBadge)
        .where(UserBadge.user_id == user_id)
        .order_by(UserBadge.earned_at.desc())
    )
    return result.scalars().all()


async def award_badge(
    db: AsyncSession,
    user_id: int,
    badge_id: int,
) -> UserBadge:
    """Award a badge to a user."""
    # Check if user already has this badge
    existing = await db.execute(
        select(UserBadge).where(
            UserBadge.user_id == user_id,
            UserBadge.badge_id == badge_id
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("User already has this badge")
    
    user_badge = UserBadge(user_id=user_id, badge_id=badge_id)
    db.add(user_badge)
    await db.commit()
    await db.refresh(user_badge)
    return user_badge


async def log_user_activity(
    db: AsyncSession,
    user_id: int,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
) -> UserActivityLog:
    """Log user activity."""
    log = UserActivityLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details or {},
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def get_user_activity(
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
) -> list[UserActivityLog]:
    """Get recent user activity."""
    result = await db.execute(
        select(UserActivityLog)
        .where(UserActivityLog.user_id == user_id)
        .order_by(UserActivityLog.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_all_badges(db: AsyncSession) -> list[Badge]:
    """Get all available badges."""
    result = await db.execute(
        select(Badge).order_by(Badge.category, Badge.name)
    )
    return result.scalars().all()


async def get_badge(db: AsyncSession, badge_id: int) -> Optional[Badge]:
    """Get a specific badge."""
    result = await db.execute(
        select(Badge).where(Badge.id == badge_id)
    )
    return result.scalar_one_or_none()
