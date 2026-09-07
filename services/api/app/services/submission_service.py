"""Submission and scoring service for OxBlood v2.

Handles flag submissions, evidence uploads, scoring with time decay,
leaderboard generation, and first blood tracking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_oxblood import (
    Submission, FlagSubmission, EvidenceSubmission, Score, ScoreHistory,
    FirstBlood, LabFlag, Lab, Drill, DrillParticipant,
    SubmissionStatus, EvidenceType,
)


# ============================================================================
# Flag Submission & Validation
# ============================================================================

async def submit_flag(
    db: AsyncSession,
    user_id: int,
    drill_id: Optional[int],
    lab_id: Optional[int],
    lab_flag_id: int,
    flag_value: str,
    hints_used: int = 0,
    team_id: Optional[int] = None,
) -> dict:
    """Submit a flag and calculate points."""
    # Get the flag
    flag_result = await db.execute(
        select(LabFlag).where(LabFlag.id == lab_flag_id)
    )
    lab_flag = flag_result.scalar_one_or_none()
    if not lab_flag:
        raise ValueError("Flag not found")
    
    # Get drill start time for time decay calculation
    elapsed_seconds = 0
    if drill_id:
        drill_result = await db.execute(
            select(Drill).where(Drill.id == drill_id)
        )
        drill = drill_result.scalar_one_or_none()
        if drill and drill.actual_start_at:
            now = datetime.now(timezone.utc)
            elapsed_seconds = int((now - drill.actual_start_at).total_seconds())
    
    # Validate flag
    is_correct = (flag_value.strip() == lab_flag.value.strip())
    
    # Calculate points
    points_earned = 0
    time_decay_factor = 1.0
    if is_correct:
        time_decay_factor = calculate_time_decay(elapsed_seconds, lab_flag.decay_window_seconds)
        points_earned = calculate_flag_points(lab_flag, time_decay_factor, hints_used)
    
    # Create parent submission
    submission = Submission(
        user_id=user_id,
        drill_id=drill_id,
        lab_id=lab_id or lab_flag.lab_id,
        team_id=team_id,
        submission_type="flag",
        status=SubmissionStatus.CORRECT if is_correct else SubmissionStatus.INCORRECT,
    )
    db.add(submission)
    await db.flush()  # Get submission.id
    
    # Get attempt number
    attempt_result = await db.execute(
        select(func.count(FlagSubmission.id)).where(
            FlagSubmission.lab_flag_id == lab_flag_id
        )
    )
    attempt_number = attempt_result.scalar() + 1
    
    # Create flag submission record
    flag_submission = FlagSubmission(
        submission_id=submission.id,
        lab_flag_id=lab_flag_id,
        flag_value=flag_value,
        is_correct=is_correct,
        points_earned=points_earned,
        time_decay_factor=time_decay_factor,
        attempt_number=attempt_number,
        hints_used=hints_used,
    )
    db.add(flag_submission)
    
    # Update score if correct
    if is_correct and drill_id:
        await update_user_score(db, user_id, drill_id, points_earned, "flag_capture", team_id)
        
        # Check for first blood
        await check_and_record_first_blood(db, drill_id, lab_flag_id, user_id, team_id)
    
    await db.commit()
    await db.refresh(submission)
    await db.refresh(flag_submission)
    
    return {
        "submission_id": submission.id,
        "is_correct": is_correct,
        "points_earned": points_earned,
        "time_decay_factor": float(time_decay_factor),
        "attempt_number": attempt_number,
    }


def calculate_time_decay(elapsed_seconds: int, decay_window: int) -> float:
    """Calculate time decay factor.
    
    Formula: max(0.5, 1 - (elapsed / decay_window))
    Minimum factor is 0.5 (50% of base points).
    """
    if decay_window <= 0:
        return 1.0
    factor = max(0.5, 1 - (elapsed_seconds / decay_window))
    return round(factor, 2)


def calculate_flag_points(lab_flag: LabFlag, time_decay_factor: float, hints_used: int) -> int:
    """Calculate final points for a flag capture.
    
    Formula: (base_points * time_decay) - (hints_used * hint_penalty)
    Minimum 0 points.
    """
    base_points = lab_flag.points
    points_after_decay = base_points * time_decay_factor
    hint_penalty = hints_used * lab_flag.hint_penalty
    final_points = max(0, points_after_decay - hint_penalty)
    return int(final_points)


async def check_and_record_first_blood(
    db: AsyncSession,
    drill_id: int,
    lab_flag_id: int,
    user_id: int,
    team_id: Optional[int] = None,
) -> Optional[FirstBlood]:
    """Check if this is the first capture and record it."""
    # Check if first blood already exists
    existing = await db.execute(
        select(FirstBlood).where(
            FirstBlood.drill_id == drill_id,
            FirstBlood.lab_flag_id == lab_flag_id,
        )
    )
    if existing.scalar_one_or_none():
        return None  # Already claimed
    
    # Record first blood
    first_blood = FirstBlood(
        drill_id=drill_id,
        lab_flag_id=lab_flag_id,
        user_id=user_id,
        team_id=team_id,
    )
    db.add(first_blood)
    await db.flush()
    return first_blood


# ============================================================================
# Submission Queries
# ============================================================================

async def list_user_submissions(
    db: AsyncSession,
    user_id: int,
    drill_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Submission]:
    """List user's submissions with optional drill filter."""
    query = select(Submission).where(Submission.user_id == user_id)
    if drill_id:
        query = query.where(Submission.drill_id == drill_id)
    query = query.order_by(Submission.submitted_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_submission(db: AsyncSession, submission_id: int) -> Optional[Submission]:
    """Get a submission by ID."""
    result = await db.execute(
        select(Submission).where(Submission.id == submission_id)
    )
    return result.scalar_one_or_none()


async def get_flag_submission(db: AsyncSession, submission_id: int) -> Optional[FlagSubmission]:
    """Get flag submission details."""
    result = await db.execute(
        select(FlagSubmission).where(FlagSubmission.submission_id == submission_id)
    )
    return result.scalar_one_or_none()


# ============================================================================
# Evidence Management
# ============================================================================

async def upload_evidence(
    db: AsyncSession,
    submission_id: int,
    evidence_type: EvidenceType,
    file_path: str,
    file_size: int,
    mime_type: Optional[str] = None,
    description: Optional[str] = None,
    objective_id: Optional[int] = None,
) -> EvidenceSubmission:
    """Upload evidence for a submission."""
    # Verify submission exists
    submission = await get_submission(db, submission_id)
    if not submission:
        raise ValueError("Submission not found")
    
    evidence = EvidenceSubmission(
        submission_id=submission_id,
        objective_id=objective_id,
        evidence_type=evidence_type,
        file_path=file_path,
        file_size=file_size,
        mime_type=mime_type,
        description=description,
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return evidence


async def list_submission_evidence(
    db: AsyncSession,
    submission_id: int,
) -> list[EvidenceSubmission]:
    """List all evidence for a submission."""
    result = await db.execute(
        select(EvidenceSubmission).where(
            EvidenceSubmission.submission_id == submission_id
        )
    )
    return result.scalars().all()


# ============================================================================
# Score Management
# ============================================================================

async def update_user_score(
    db: AsyncSession,
    user_id: int,
    drill_id: int,
    points_earned: int,
    action: str,
    team_id: Optional[int] = None,
) -> Score:
    """Update user's score for a drill."""
    # Get or create score record
    result = await db.execute(
        select(Score).where(
            Score.user_id == user_id,
            Score.drill_id == drill_id,
        )
    )
    score = result.scalar_one_or_none()
    
    if score:
        previous_total = score.total_points
        score.total_points += points_earned
        if "flag" in action:
            score.flags_captured += 1
        score.last_updated_at = datetime.now(timezone.utc)
    else:
        previous_total = 0
        score = Score(
            user_id=user_id,
            drill_id=drill_id,
            team_id=team_id,
            total_points=points_earned,
            flags_captured=1 if "flag" in action else 0,
        )
        db.add(score)
        await db.flush()
    
    # Record score history
    history = ScoreHistory(
        user_id=user_id,
        drill_id=drill_id,
        team_id=team_id,
        action=action,
        points_change=points_earned,
        previous_total=previous_total,
        new_total=score.total_points,
        details={"points_earned": points_earned},
    )
    db.add(history)
    
    return score


async def get_drill_scores(db: AsyncSession, drill_id: int) -> list[Score]:
    """Get all scores for a drill, ordered by rank."""
    result = await db.execute(
        select(Score)
        .where(Score.drill_id == drill_id)
        .order_by(Score.total_points.desc())
    )
    return result.scalars().all()


async def get_user_scores(db: AsyncSession, user_id: int) -> list[Score]:
    """Get all scores for a user across drills."""
    result = await db.execute(
        select(Score)
        .where(Score.user_id == user_id)
        .order_by(Score.last_updated_at.desc())
    )
    return result.scalars().all()


async def get_leaderboard(
    db: AsyncSession,
    drill_id: Optional[int] = None,
    limit: int = 100,
) -> list[dict]:
    """Get leaderboard with user details."""
    if drill_id:
        # Drill-specific leaderboard
        result = await db.execute(
            select(Score)
            .where(Score.drill_id == drill_id)
            .order_by(Score.total_points.desc())
            .limit(limit)
        )
        scores = result.scalars().all()
        
        leaderboard = []
        for rank, score in enumerate(scores, 1):
            leaderboard.append({
                "rank": rank,
                "user_id": score.user_id,
                "total_points": score.total_points,
                "flags_captured": score.flags_captured,
                "completion_time_seconds": score.completion_time_seconds,
            })
        return leaderboard
    else:
        # Global leaderboard - aggregate all scores
        result = await db.execute(
            select(
                Score.user_id,
                func.sum(Score.total_points).label("total_points"),
                func.sum(Score.flags_captured).label("total_flags"),
            )
            .group_by(Score.user_id)
            .order_by(func.sum(Score.total_points).desc())
            .limit(limit)
        )
        rows = result.all()
        
        leaderboard = []
        for rank, row in enumerate(rows, 1):
            leaderboard.append({
                "rank": rank,
                "user_id": row.user_id,
                "total_points": int(row.total_points or 0),
                "flags_captured": int(row.total_flags or 0),
            })
        return leaderboard


async def get_score_history(
    db: AsyncSession,
    user_id: int,
    drill_id: Optional[int] = None,
) -> list[ScoreHistory]:
    """Get score change history."""
    query = select(ScoreHistory).where(ScoreHistory.user_id == user_id)
    if drill_id:
        query = query.where(ScoreHistory.drill_id == drill_id)
    query = query.order_by(ScoreHistory.recorded_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


# ============================================================================
# First Blood
# ============================================================================

async def get_drill_first_bloods(db: AsyncSession, drill_id: int) -> list[FirstBlood]:
    """Get all first blood records for a drill."""
    result = await db.execute(
        select(FirstBlood)
        .where(FirstBlood.drill_id == drill_id)
        .order_by(FirstBlood.captured_at)
    )
    return result.scalars().all()


async def get_user_first_bloods(db: AsyncSession, user_id: int) -> list[FirstBlood]:
    """Get all first bloods achieved by a user."""
    result = await db.execute(
        select(FirstBlood)
        .where(FirstBlood.user_id == user_id)
        .order_by(FirstBlood.captured_at.desc())
    )
    return result.scalars().all()


# ============================================================================
# Statistics
# ============================================================================

async def get_drill_stats(db: AsyncSession, drill_id: int) -> dict:
    """Get statistics for a drill."""
    # Total participants
    participant_result = await db.execute(
        select(func.count(DrillParticipant.id)).where(
            DrillParticipant.drill_id == drill_id
        )
    )
    total_participants = participant_result.scalar() or 0
    
    # Total submissions
    submission_result = await db.execute(
        select(func.count(Submission.id)).where(
            Submission.drill_id == drill_id
        )
    )
    total_submissions = submission_result.scalar() or 0
    
    # Correct submissions
    correct_result = await db.execute(
        select(func.count(Submission.id)).where(
            Submission.drill_id == drill_id,
            Submission.status == SubmissionStatus.CORRECT,
        )
    )
    correct_submissions = correct_result.scalar() or 0
    
    # Total flags available
    drill_result = await db.execute(
        select(Drill).where(Drill.id == drill_id)
    )
    drill = drill_result.scalar_one_or_none()
    total_flags = 0
    if drill and drill.lab_id:
        flag_result = await db.execute(
            select(func.count(LabFlag.id)).where(
                LabFlag.lab_id == drill.lab_id
            )
        )
        total_flags = flag_result.scalar() or 0
    
    # First bloods claimed
    first_blood_result = await db.execute(
        select(func.count(FirstBlood.id)).where(
            FirstBlood.drill_id == drill_id
        )
    )
    first_bloods_claimed = first_blood_result.scalar() or 0
    
    return {
        "total_participants": total_participants,
        "total_submissions": total_submissions,
        "correct_submissions": correct_submissions,
        "total_flags": total_flags,
        "first_bloods_claimed": first_bloods_claimed,
        "success_rate": round((correct_submissions / total_submissions * 100), 2) if total_submissions > 0 else 0,
    }


async def get_user_stats(db: AsyncSession, user_id: int) -> dict:
    """Get statistics for a user."""
    # Total score across all drills
    score_result = await db.execute(
        select(
            func.sum(Score.total_points).label("total_points"),
            func.sum(Score.flags_captured).label("total_flags"),
            func.count(Score.id).label("drills_participated"),
        ).where(Score.user_id == user_id)
    )
    score_row = score_result.one()
    
    # First bloods achieved
    first_blood_result = await db.execute(
        select(func.count(FirstBlood.id)).where(
            FirstBlood.user_id == user_id
        )
    )
    first_bloods = first_blood_result.scalar() or 0
    
    # Total submissions
    submission_result = await db.execute(
        select(func.count(Submission.id)).where(
            Submission.user_id == user_id
        )
    )
    total_submissions = submission_result.scalar() or 0
    
    return {
        "total_points": int(score_row.total_points or 0),
        "total_flags": int(score_row.total_flags or 0),
        "drills_participated": int(score_row.drills_participated or 0),
        "first_bloods": first_bloods,
        "total_submissions": total_submissions,
    }
