"""Reports and benchmarks router for OxBlood v2.

Provides endpoints for report management, findings, evidence, and benchmarks.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models_oxblood import ReportStatus, SeverityLevel, EvidenceType
from app.services.report_service import (
    list_reports, get_report, create_report, update_report, submit_report, grade_report,
    list_findings, create_finding, update_finding, delete_finding,
    list_finding_evidence, add_evidence, delete_evidence,
    get_user_benchmark, calculate_and_update_benchmark, get_benchmark_history, get_global_benchmarks,
)

router = APIRouter(prefix="/api/v2", tags=["Reports & Benchmarks v2"])


# ============================================================================
# Pydantic Models
# ============================================================================

class ReportCreate(BaseModel):
    title: str
    summary: str
    content: str
    drill_id: Optional[int] = None
    user_id: Optional[int] = None
    team_id: Optional[int] = None
    report_type: str = "after_action"


class ReportUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None


class ReportGrade(BaseModel):
    graded_by: int
    quality_score: float
    grade: str
    feedback: Optional[str] = None


class FindingCreate(BaseModel):
    title: str
    description: str
    severity: SeverityLevel
    category: Optional[str] = None
    evidence: Optional[str] = None
    impact: Optional[str] = None
    recommendation: Optional[str] = None
    cvss_score: Optional[float] = None
    cwe_id: Optional[str] = None
    sort_order: int = 0


class FindingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[SeverityLevel] = None
    category: Optional[str] = None
    evidence: Optional[str] = None
    impact: Optional[str] = None
    recommendation: Optional[str] = None
    cvss_score: Optional[float] = None
    cwe_id: Optional[str] = None
    sort_order: Optional[int] = None


class EvidenceCreate(BaseModel):
    evidence_type: EvidenceType
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    description: Optional[str] = None


# ============================================================================
# Helper Functions
# ============================================================================

def report_to_dict(report) -> dict:
    """Convert report to dict."""
    return {
        "id": report.id,
        "drill_id": report.drill_id,
        "user_id": report.user_id,
        "team_id": report.team_id,
        "title": report.title,
        "summary": report.summary,
        "content": report.content,
        "status": report.status.value if hasattr(report.status, "value") else report.status,
        "report_type": report.report_type,
        "quality_score": float(report.quality_score) if report.quality_score else None,
        "grade": report.grade,
        "word_count": report.word_count,
        "file_path": report.file_path,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "graded_at": report.graded_at.isoformat() if report.graded_at else None,
        "graded_by": report.graded_by,
        "instructor_feedback": report.instructor_feedback,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


def finding_to_dict(finding) -> dict:
    """Convert finding to dict."""
    return {
        "id": finding.id,
        "report_id": finding.report_id,
        "title": finding.title,
        "description": finding.description,
        "severity": finding.severity.value if hasattr(finding.severity, "value") else finding.severity,
        "category": finding.category,
        "evidence": finding.evidence,
        "impact": finding.impact,
        "recommendation": finding.recommendation,
        "cvss_score": float(finding.cvss_score) if finding.cvss_score else None,
        "cwe_id": finding.cwe_id,
        "sort_order": finding.sort_order,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


def evidence_to_dict(evidence) -> dict:
    """Convert evidence to dict."""
    return {
        "id": evidence.id,
        "finding_id": evidence.finding_id,
        "evidence_type": evidence.evidence_type.value if hasattr(evidence.evidence_type, "value") else evidence.evidence_type,
        "file_path": evidence.file_path,
        "file_size": evidence.file_size,
        "mime_type": evidence.mime_type,
        "description": evidence.description,
        "captured_at": evidence.captured_at.isoformat() if evidence.captured_at else None,
        "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
    }


def benchmark_to_dict(benchmark) -> dict:
    """Convert benchmark to dict."""
    return {
        "id": benchmark.id,
        "user_id": benchmark.user_id,
        "overall_score": float(benchmark.overall_score),
        "offensive_score": float(benchmark.offensive_score),
        "defensive_score": float(benchmark.defensive_score),
        "web_exploitation_score": float(benchmark.web_exploitation_score),
        "network_exploitation_score": float(benchmark.network_exploitation_score),
        "active_directory_score": float(benchmark.active_directory_score),
        "linux_score": float(benchmark.linux_score),
        "windows_score": float(benchmark.windows_score),
        "forensics_score": float(benchmark.forensics_score),
        "reporting_score": float(benchmark.reporting_score),
        "total_drills_completed": benchmark.total_drills_completed,
        "total_flags_captured": benchmark.total_flags_captured,
        "average_completion_time_seconds": benchmark.average_completion_time_seconds,
        "last_calculated_at": benchmark.last_calculated_at.isoformat() if benchmark.last_calculated_at else None,
    }


def benchmark_history_to_dict(history) -> dict:
    """Convert benchmark history to dict."""
    return {
        "id": history.id,
        "user_id": history.user_id,
        "drill_id": history.drill_id,
        "overall_score": float(history.overall_score),
        "offensive_score": float(history.offensive_score),
        "defensive_score": float(history.defensive_score),
        "web_exploitation_score": float(history.web_exploitation_score),
        "network_exploitation_score": float(history.network_exploitation_score),
        "active_directory_score": float(history.active_directory_score),
        "linux_score": float(history.linux_score),
        "windows_score": float(history.windows_score),
        "forensics_score": float(history.forensics_score),
        "reporting_score": float(history.reporting_score),
        "calculated_at": history.calculated_at.isoformat() if history.calculated_at else None,
    }


# ============================================================================
# Reports Endpoints
# ============================================================================

@router.post("/reports")
async def post_report(
    data: ReportCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new report."""
    report = await create_report(
        session,
        title=data.title,
        summary=data.summary,
        content=data.content,
        drill_id=data.drill_id,
        user_id=data.user_id,
        team_id=data.team_id,
        report_type=data.report_type,
    )
    return {"message": "Report created", "report_id": report.id}


@router.get("/reports")
async def get_reports(
    user_id: Optional[int] = Query(None, description="Filter by user"),
    drill_id: Optional[int] = Query(None, description="Filter by drill"),
    status: Optional[ReportStatus] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List reports with optional filters."""
    reports = await list_reports(session, user_id, drill_id, status, skip, limit)
    return {
        "reports": [report_to_dict(r) for r in reports],
        "count": len(reports),
    }


@router.get("/reports/{report_id}")
async def get_report_details(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get report details with findings."""
    report = await get_report(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    findings = await list_findings(session, report_id)
    result = report_to_dict(report)
    result["findings"] = [finding_to_dict(f) for f in findings]
    result["findings_count"] = len(findings)
    return result


@router.put("/reports/{report_id}")
async def put_report(
    report_id: int,
    data: ReportUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a report."""
    report = await update_report(
        session,
        report_id,
        title=data.title,
        summary=data.summary,
        content=data.content,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"message": "Report updated", "report_id": report.id}


@router.post("/reports/{report_id}/submit")
async def post_report_submit(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Submit a report for review."""
    report = await submit_report(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"message": "Report submitted for review", "status": report.status.value if hasattr(report.status, "value") else report.status}


@router.post("/reports/{report_id}/grade")
async def post_report_grade(
    report_id: int,
    data: ReportGrade,
    session: AsyncSession = Depends(get_session),
):
    """Grade a submitted report."""
    report = await grade_report(
        session,
        report_id,
        graded_by=data.graded_by,
        quality_score=data.quality_score,
        grade=data.grade,
        feedback=data.feedback,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "message": "Report graded",
        "quality_score": float(report.quality_score) if report.quality_score else None,
        "grade": report.grade,
    }


# ============================================================================
# Findings Endpoints
# ============================================================================

@router.get("/reports/{report_id}/findings")
async def get_findings(
    report_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List all findings for a report."""
    report = await get_report(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    findings = await list_findings(session, report_id)
    return {
        "findings": [finding_to_dict(f) for f in findings],
        "count": len(findings),
    }


@router.post("/reports/{report_id}/findings")
async def post_finding(
    report_id: int,
    data: FindingCreate,
    session: AsyncSession = Depends(get_session),
):
    """Add a finding to a report."""
    report = await get_report(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    finding = await create_finding(
        session,
        report_id=report_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        category=data.category,
        evidence=data.evidence,
        impact=data.impact,
        recommendation=data.recommendation,
        cvss_score=data.cvss_score,
        cwe_id=data.cwe_id,
        sort_order=data.sort_order,
    )
    return {"message": "Finding added", "finding_id": finding.id}


@router.put("/reports/findings/{finding_id}")
async def put_finding(
    finding_id: int,
    data: FindingUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a finding."""
    finding = await update_finding(
        session,
        finding_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        category=data.category,
        evidence=data.evidence,
        impact=data.impact,
        recommendation=data.recommendation,
        cvss_score=data.cvss_score,
        cwe_id=data.cwe_id,
        sort_order=data.sort_order,
    )
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return {"message": "Finding updated", "finding_id": finding.id}


@router.delete("/reports/findings/{finding_id}")
async def delete_finding_endpoint(
    finding_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a finding."""
    deleted = await delete_finding(session, finding_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Finding not found")
    return {"message": "Finding deleted"}


# ============================================================================
# Evidence Endpoints
# ============================================================================

@router.get("/reports/findings/{finding_id}/evidence")
async def get_finding_evidence(
    finding_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List all evidence for a finding."""
    evidence_list = await list_finding_evidence(session, finding_id)
    return {
        "evidence": [evidence_to_dict(e) for e in evidence_list],
        "count": len(evidence_list),
    }


@router.post("/reports/findings/{finding_id}/evidence")
async def post_finding_evidence(
    finding_id: int,
    data: EvidenceCreate,
    session: AsyncSession = Depends(get_session),
):
    """Add evidence to a finding."""
    evidence = await add_evidence(
        session,
        finding_id=finding_id,
        evidence_type=data.evidence_type,
        file_path=data.file_path,
        file_size=data.file_size,
        mime_type=data.mime_type,
        description=data.description,
    )
    return {"message": "Evidence added", "evidence_id": evidence.id}


@router.delete("/reports/evidence/{evidence_id}")
async def delete_evidence_endpoint(
    evidence_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete evidence."""
    deleted = await delete_evidence(session, evidence_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return {"message": "Evidence deleted"}


# ============================================================================
# Benchmarks Endpoints
# ============================================================================

@router.get("/users/{user_id}/benchmarks")
async def get_user_benchmark_endpoint(
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get current benchmark for a user."""
    benchmark = await get_user_benchmark(session, user_id)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return benchmark_to_dict(benchmark)


@router.post("/users/{user_id}/benchmarks/calculate")
async def post_calculate_benchmark(
    user_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Calculate and update user's benchmark."""
    benchmark = await calculate_and_update_benchmark(session, user_id)
    return {
        "message": "Benchmark calculated",
        "benchmark": benchmark_to_dict(benchmark),
    }


@router.get("/users/{user_id}/benchmarks/history")
async def get_benchmark_history_endpoint(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Get benchmark history for a user."""
    history = await get_benchmark_history(session, user_id, limit)
    return {
        "history": [benchmark_history_to_dict(h) for h in history],
        "count": len(history),
    }


@router.get("/benchmarks")
async def get_global_benchmarks_endpoint(
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """Get global benchmarks ranked by overall score."""
    benchmarks = await get_global_benchmarks(session, limit)
    return {
        "benchmarks": [benchmark_to_dict(b) for b in benchmarks],
        "count": len(benchmarks),
    }
