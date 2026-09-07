"""Report and benchmark service for OxBlood v2.

Handles report CRUD, findings management, evidence tracking, report grading,
and benchmark calculation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_oxblood import (
    Report, ReportFinding, Evidence, Benchmark, BenchmarkHistory,
    ReportStatus, SeverityLevel, EvidenceType,
)


# ============================================================================
# Report CRUD
# ============================================================================

async def list_reports(
    db: AsyncSession,
    user_id: Optional[int] = None,
    drill_id: Optional[int] = None,
    status: Optional[ReportStatus] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[Report]:
    """List reports with optional filters."""
    query = select(Report)
    if user_id:
        query = query.where(Report.user_id == user_id)
    if drill_id:
        query = query.where(Report.drill_id == drill_id)
    if status:
        query = query.where(Report.status == status)
    query = query.order_by(Report.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_report(db: AsyncSession, report_id: int) -> Optional[Report]:
    """Get a report by ID."""
    result = await db.execute(
        select(Report).where(Report.id == report_id)
    )
    return result.scalar_one_or_none()


async def create_report(
    db: AsyncSession,
    title: str,
    summary: str,
    content: str,
    drill_id: Optional[int] = None,
    user_id: Optional[int] = None,
    team_id: Optional[int] = None,
    report_type: str = "after_action",
) -> Report:
    """Create a new report."""
    report = Report(
        title=title,
        summary=summary,
        content=content,
        drill_id=drill_id,
        user_id=user_id,
        team_id=team_id,
        report_type=report_type,
        status=ReportStatus.DRAFT,
        word_count=len(content.split()),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def update_report(
    db: AsyncSession,
    report_id: int,
    **kwargs
) -> Optional[Report]:
    """Update a report."""
    report = await get_report(db, report_id)
    if not report:
        return None
    for key, value in kwargs.items():
        if hasattr(report, key) and value is not None:
            setattr(report, key, value)
    # Recalculate word count if content changed
    if "content" in kwargs:
        report.word_count = len(report.content.split())
    await db.commit()
    await db.refresh(report)
    return report


async def submit_report(db: AsyncSession, report_id: int) -> Optional[Report]:
    """Submit a report for review."""
    report = await get_report(db, report_id)
    if not report:
        return None
    report.status = ReportStatus.SUBMITTED
    report.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    return report


async def grade_report(
    db: AsyncSession,
    report_id: int,
    graded_by: int,
    quality_score: float,
    grade: str,
    feedback: Optional[str] = None,
) -> Optional[Report]:
    """Grade a submitted report."""
    report = await get_report(db, report_id)
    if not report:
        return None
    report.status = ReportStatus.GRADED
    report.graded_at = datetime.now(timezone.utc)
    report.graded_by = graded_by
    report.quality_score = quality_score
    report.grade = grade
    report.instructor_feedback = feedback
    await db.commit()
    await db.refresh(report)
    return report


# ============================================================================
# Report Findings
# ============================================================================

async def list_findings(db: AsyncSession, report_id: int) -> list[ReportFinding]:
    """List all findings for a report."""
    result = await db.execute(
        select(ReportFinding)
        .where(ReportFinding.report_id == report_id)
        .order_by(ReportFinding.sort_order)
    )
    return result.scalars().all()


async def create_finding(
    db: AsyncSession,
    report_id: int,
    title: str,
    description: str,
    severity: SeverityLevel,
    category: Optional[str] = None,
    evidence: Optional[str] = None,
    impact: Optional[str] = None,
    recommendation: Optional[str] = None,
    cvss_score: Optional[float] = None,
    cwe_id: Optional[str] = None,
    sort_order: int = 0,
) -> ReportFinding:
    """Add a finding to a report."""
    finding = ReportFinding(
        report_id=report_id,
        title=title,
        description=description,
        severity=severity,
        category=category,
        evidence=evidence,
        impact=impact,
        recommendation=recommendation,
        cvss_score=cvss_score,
        cwe_id=cwe_id,
        sort_order=sort_order,
    )
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


async def update_finding(
    db: AsyncSession,
    finding_id: int,
    **kwargs
) -> Optional[ReportFinding]:
    """Update a finding."""
    result = await db.execute(
        select(ReportFinding).where(ReportFinding.id == finding_id)
    )
    finding = result.scalar_one_or_none()
    if not finding:
        return None
    for key, value in kwargs.items():
        if hasattr(finding, key) and value is not None:
            setattr(finding, key, value)
    await db.commit()
    await db.refresh(finding)
    return finding


async def delete_finding(db: AsyncSession, finding_id: int) -> bool:
    """Delete a finding."""
    result = await db.execute(
        select(ReportFinding).where(ReportFinding.id == finding_id)
    )
    finding = result.scalar_one_or_none()
    if not finding:
        return False
    await db.delete(finding)
    await db.commit()
    return True


# ============================================================================
# Evidence Management
# ============================================================================

async def list_finding_evidence(db: AsyncSession, finding_id: int) -> list[Evidence]:
    """List all evidence for a finding."""
    result = await db.execute(
        select(Evidence).where(Evidence.finding_id == finding_id)
    )
    return result.scalars().all()


async def add_evidence(
    db: AsyncSession,
    finding_id: int,
    evidence_type: EvidenceType,
    file_path: str,
    file_size: int,
    mime_type: Optional[str] = None,
    description: Optional[str] = None,
) -> Evidence:
    """Add evidence to a finding."""
    evidence = Evidence(
        finding_id=finding_id,
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


async def delete_evidence(db: AsyncSession, evidence_id: int) -> bool:
    """Delete evidence."""
    result = await db.execute(
        select(Evidence).where(Evidence.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    if not evidence:
        return False
    await db.delete(evidence)
    await db.commit()
    return True


# ============================================================================
# Benchmarks
# ============================================================================

async def get_user_benchmark(db: AsyncSession, user_id: int) -> Optional[Benchmark]:
    """Get current benchmark for a user."""
    result = await db.execute(
        select(Benchmark).where(Benchmark.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def calculate_and_update_benchmark(
    db: AsyncSession,
    user_id: int,
) -> Benchmark:
    """Calculate and update user's benchmark based on their performance."""
    from app.db.models_oxblood import Score, FirstBlood
    
    # Get user's scores
    score_result = await db.execute(
        select(
            func.sum(Score.total_points).label("total_points"),
            func.sum(Score.flags_captured).label("total_flags"),
            func.avg(Score.completion_time_seconds).label("avg_time"),
            func.count(Score.id).label("drills_completed"),
        ).where(Score.user_id == user_id)
    )
    score_row = score_result.one()
    
    total_points = float(score_row.total_points or 0)
    total_flags = int(score_row.total_flags or 0)
    avg_time = float(score_row.avg_time or 0)
    drills_completed = int(score_row.drills_completed or 0)
    
    # Calculate category scores (simplified - in production, this would be more sophisticated)
    # For now, use total_points as a base and distribute across categories
    base_score = min(100, total_points / 10)  # Normalize to 0-100
    
    # Get or create benchmark
    benchmark = await get_user_benchmark(db, user_id)
    if not benchmark:
        benchmark = Benchmark(user_id=user_id)
        db.add(benchmark)
    
    # Update scores
    benchmark.overall_score = base_score
    benchmark.offensive_score = base_score * 0.9  # Offensive slightly lower
    benchmark.defensive_score = base_score * 0.8  # Defensive slightly lower
    benchmark.web_exploitation_score = base_score * 0.85
    benchmark.network_exploitation_score = base_score * 0.80
    benchmark.active_directory_score = base_score * 0.75
    benchmark.linux_score = base_score * 0.82
    benchmark.windows_score = base_score * 0.78
    benchmark.forensics_score = base_score * 0.70
    benchmark.reporting_score = base_score * 0.88
    benchmark.total_drills_completed = drills_completed
    benchmark.total_flags_captured = total_flags
    benchmark.average_completion_time_seconds = int(avg_time) if avg_time > 0 else None
    benchmark.last_calculated_at = datetime.now(timezone.utc)
    
    await db.flush()
    
    # Record in history
    history = BenchmarkHistory(
        user_id=user_id,
        overall_score=benchmark.overall_score,
        offensive_score=benchmark.offensive_score,
        defensive_score=benchmark.defensive_score,
        web_exploitation_score=benchmark.web_exploitation_score,
        network_exploitation_score=benchmark.network_exploitation_score,
        active_directory_score=benchmark.active_directory_score,
        linux_score=benchmark.linux_score,
        windows_score=benchmark.windows_score,
        forensics_score=benchmark.forensics_score,
        reporting_score=benchmark.reporting_score,
    )
    db.add(history)
    
    await db.commit()
    await db.refresh(benchmark)
    return benchmark


async def get_benchmark_history(
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
) -> list[BenchmarkHistory]:
    """Get benchmark history for a user."""
    result = await db.execute(
        select(BenchmarkHistory)
        .where(BenchmarkHistory.user_id == user_id)
        .order_by(BenchmarkHistory.calculated_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_global_benchmarks(
    db: AsyncSession,
    limit: int = 100,
) -> list[Benchmark]:
    """Get global benchmarks ranked by overall score."""
    result = await db.execute(
        select(Benchmark)
        .order_by(Benchmark.overall_score.desc())
        .limit(limit)
    )
    return result.scalars().all()
