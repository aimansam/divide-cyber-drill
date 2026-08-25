"""F11: drill debrief artifact.

Returns a markdown play-by-play of a finished drill for hand-off
to leadership. Sections:

  1. Summary -- scenario, outcome, started_by, duration.
  2. Per-team score -- red vs blue, with leaderboard callout.
  3. Per-flag timing -- capture time + decay-adjusted points.
  4. Pivot timeline -- red-team events (run.started, asset.running,
     flag.captured, kill-chain.signal).
  5. Detection timeline -- blue-team events (defensive wins).
  6. Asset capture table -- role, template, status, IP, error.
  7. Lessons learned placeholder for the operator to fill in.

Auth + RBAC mirrors ``/runs/{id}/report`` (the JSON sibling);
see ``app.routers.reports``. Status codes:

  * 200 -- debrief delivered.
  * 401 -- no token.
  * 403 -- token cannot see this run.
  * 404 -- run id does not exist.
  * 409 -- run is still in a non-terminal state.
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.session import get_session
from app.services.authorization import can_view_run

router = APIRouter()


# --- public endpoint -----------------------------------------------------

@router.get(
    "/{run_id}/debrief.md",
    summary="Get a markdown debrief for a finished drill (F11).",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_debrief(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> PlainTextResponse:
    """Render the drill as a markdown debrief.

    Mirrors the JSON ``/runs/{id}/report`` contract; same
    visibility rules + same 409-on-non-terminal gate.
    """
    run = await _load_run_or_404(session, run_id)
    if not can_view_run(token, run):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this run",
        )
    if run.status in (db_models.RunStatus.PENDING, db_models.RunStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"run id={run_id} is in non-terminal state "
                f"{run.status.value!r}; debrief is for completed runs only"
            ),
        )

    md = await _render_debrief(session, run)
    return PlainTextResponse(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="run-{run_id}-debrief.md"'},
    )


# --- helpers -------------------------------------------------------------

async def _load_run_or_404(
    session: AsyncSession, run_id: int
) -> db_models.Run:
    stmt = select(db_models.Run).where(db_models.Run.id == run_id)
    run = (await session.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )
    return run


async def _render_debrief(
    session: AsyncSession, run: db_models.Run
) -> str:
    """Assemble the full markdown document.

    Pulls the scenario, asset, flag_submission, and telemetry_event
    rows in four queries -- the debrief is generated on demand and
    the joins are small enough that four round-trips is fine.
    """
    scenario = await _load_scenario(session, run.scenario_id)
    assets = await _load_assets(session, run.id)
    submissions = await _load_submissions(session, run.id)
    telemetry = await _load_telemetry(session, run.id)

    buf = io.StringIO()
    _render_summary(buf, run, scenario)
    _render_scores(buf, run, submissions)
    _render_flag_timing(buf, submissions)
    _render_pivot_timeline(buf, telemetry)
    _render_detection_timeline(buf, telemetry)
    _render_assets(buf, assets)
    _render_lessons_learned(buf)
    return buf.getvalue()


async def _load_scenario(
    session: AsyncSession, scenario_id: int
) -> db_models.Scenario | None:
    return (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.id == scenario_id)
        )
    ).scalar_one_or_none()


async def _load_assets(
    session: AsyncSession, run_id: int
) -> list[db_models.Asset]:
    return list(
        (
            await session.execute(
                select(db_models.Asset).where(db_models.Asset.run_id == run_id)
            )
        ).scalars()
    )


async def _load_submissions(
    session: AsyncSession, run_id: int
) -> list[db_models.FlagSubmission]:
    return list(
        (
            await session.execute(
                select(db_models.FlagSubmission)
                .where(db_models.FlagSubmission.run_id == run_id)
                .order_by(db_models.FlagSubmission.captured_at.asc())
            )
        ).scalars()
    )


async def _load_telemetry(
    session: AsyncSession, run_id: int
) -> list[db_models.TelemetryEvent]:
    return list(
        (
            await session.execute(
                select(db_models.TelemetryEvent)
                .where(db_models.TelemetryEvent.run_id == run_id)
                .order_by(db_models.TelemetryEvent.ts.asc())
            )
        ).scalars()
    )


# --- markdown rendering --------------------------------------------------

def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _fmt_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _render_summary(
    buf: io.StringIO,
    run: db_models.Run,
    scenario: db_models.Scenario | None,
) -> None:
    buf.write("# Drill debrief\n\n")
    if scenario is not None:
        buf.write(f"**Scenario:** `{scenario.name}` -- {scenario.title} ")
        buf.write(f"(v{scenario.version}, {scenario.difficulty or 'n/a'}, ")
        buf.write(f"{scenario.duration_min or '?'} min)\n\n")
    else:
        buf.write(f"**Scenario id:** {run.scenario_id} (missing)\n\n")

    started = _fmt_dt(run.started_at)
    ended = _fmt_dt(run.ended_at)
    duration = _fmt_duration(run.duration_sec)

    buf.write("## Summary\n\n")
    buf.write(f"* **Run id:** `{run.id}`\n")
    buf.write(f"* **Status:** `{run.status.value}`\n")
    buf.write(f"* **Started:** {started}\n")
    buf.write(f"* **Ended:** {ended}\n")
    buf.write(f"* **Duration:** {duration}\n")
    buf.write(f"* **Started by:** {run.started_by or '-'}\n")
    if run.error:
        buf.write(f"* **Error:** `{run.error}`\n")
    buf.write("\n")


def _render_scores(
    buf: io.StringIO,
    run: db_models.Run,
    submissions: Iterable[db_models.FlagSubmission],
) -> None:
    buf.write("## Per-team score\n\n")
    score_red = run.score_red if run.score_red is not None else 0
    score_blue = run.score_blue if run.score_blue is not None else 0
    winner = (
        "red" if score_red > score_blue
        else "blue" if score_blue > score_red
        else "tied"
    )

    counts: dict[str, int] = defaultdict(int)
    points: dict[str, int] = defaultdict(int)
    for s in submissions:
        counts[s.team] += 1
        points[s.team] += s.points

    buf.write("| Team | Captures | Points (raw) | Score (decay-adjusted) |\n")
    buf.write("|------|----------|--------------|------------------------|\n")
    buf.write(
        f"| red  | {counts.get('red', 0)} | {points.get('red', 0)} | {score_red} |\n"
    )
    buf.write(
        f"| blue | {counts.get('blue', 0)} | {points.get('blue', 0)} | {score_blue} |\n"
    )
    buf.write("\n")
    if winner == "tied":
        buf.write("**Result:** tied.\n\n")
    else:
        buf.write(f"**Result:** `{winner}` wins.\n\n")


def _render_flag_timing(
    buf: io.StringIO,
    submissions: Iterable[db_models.FlagSubmission],
) -> None:
    rows = list(submissions)
    buf.write("## Per-flag timing\n\n")
    if not rows:
        buf.write("_No flags captured._\n\n")
        return
    buf.write("| Captured at | Team | Flag | Elapsed (s) | Points |\n")
    buf.write("|-------------|------|------|-------------|--------|\n")
    for s in rows:
        buf.write(
            f"| {_fmt_dt(s.captured_at)} | {s.team} | `{s.flag_id}` | "
            f"{s.elapsed_seconds} | {s.points} |\n"
        )
    buf.write("\n")


def _render_pivot_timeline(
    buf: io.StringIO,
    telemetry: Iterable[db_models.TelemetryEvent],
) -> None:
    """Red-team timeline: starts, asset.running, flag.captured, custom
    kill-chain events."""
    events = [e for e in telemetry if _is_pivot_event(e)]
    buf.write("## Pivot timeline (red)\n\n")
    if not events:
        buf.write("_No pivot events recorded._\n\n")
        return
    buf.write("| Time | Kind | Severity | Source | Detail |\n")
    buf.write("|------|------|----------|--------|--------|\n")
    for e in events:
        detail = _event_detail(e)
        buf.write(
            f"| {_fmt_dt(e.ts)} | `{e.kind}` | {e.severity.value} | "
            f"{e.source} | {detail} |\n"
        )
    buf.write("\n")


def _render_detection_timeline(
    buf: io.StringIO,
    telemetry: Iterable[db_models.TelemetryEvent],
) -> None:
    """Blue-team timeline: detections + audit-feed alerts."""
    events = [e for e in telemetry if _is_detection_event(e)]
    buf.write("## Detection timeline (blue)\n\n")
    if not events:
        buf.write("_No detection events recorded._\n\n")
        return
    buf.write("| Time | Kind | Severity | Source | Detail |\n")
    buf.write("|------|------|----------|--------|--------|\n")
    for e in events:
        detail = _event_detail(e)
        buf.write(
            f"| {_fmt_dt(e.ts)} | `{e.kind}` | {e.severity.value} | "
            f"{e.source} | {detail} |\n"
        )
    buf.write("\n")


def _is_pivot_event(e: db_models.TelemetryEvent) -> bool:
    """An event is a red-team pivot if it advances the attack:
    run lifecycle, asset acquisition, flag capture, custom
    kill-chain signal."""
    return e.kind in {
        "run.started",
        "run.completed",
        "asset.running",
        "flag.captured",
        "kill-chain.signal",
    }


def _is_detection_event(e: db_models.TelemetryEvent) -> bool:
    """An event is a blue-team detection if it's a defensive
    win (audit alert, SOC signal). For F11 we use the kind
    vocabulary; if the kind vocabulary expands, this set
    is the single point to update."""
    return e.kind in {
        "audit.alert",
        "soc.signal",
        "blue.detection",
    }


def _event_detail(e: db_models.TelemetryEvent) -> str:
    """Render the payload field (if any) as a single-line summary."""
    payload = e.payload or {}
    if not payload:
        return "-"
    bits: list[str] = []
    for key in ("asset_id", "flag_id", "team", "score", "message"):
        if key in payload:
            val = payload[key]
            bits.append(f"{key}={val}")
    if not bits:
        import json

        try:
            rendered = json.dumps(payload, default=str)
            return f"`{rendered[:80]}`" + ("..." if len(rendered) > 80 else "")
        except (TypeError, ValueError):
            return repr(payload)[:80]
    return ", ".join(bits)


def _render_assets(
    buf: io.StringIO, assets: list[db_models.Asset]
) -> None:
    buf.write("## Asset table\n\n")
    if not assets:
        buf.write("_No assets._\n\n")
        return
    buf.write("| Role | Template | Status | IP | VMID | Error |\n")
    buf.write("|------|----------|--------|----|------|-------|\n")
    for a in sorted(assets, key=lambda x: (x.role or "", x.id)):
        buf.write(
            f"| `{a.role}` | `{a.template}` | {a.status.value} | "
            f"{a.pve_ip or '-'} | {a.pve_vmid or '-'} | "
            f"{a.error or '-'} |\n"
        )
    buf.write("\n")


def _render_lessons_learned(buf: io.StringIO) -> None:
    """Empty placeholder for the operator to fill in.

    We don't try to be clever here -- leadership reads this
    section to learn from the drill. The operator fills it in
    after reviewing the timeline.
    """
    buf.write("## Lessons learned\n\n")
    buf.write("_Operator: add what worked, what surprised you, and what to_\n")
    buf.write("_change before the next cohort. Suggested prompts:_\n\n")
    buf.write("* _Did the red team find any path you didn't expect?_\n")
    buf.write("* _Did the blue team detect pivots within the SLA?_\n")
    buf.write("* _Were there tooling gaps (console, telemetry, scoring)?_\n")
    buf.write("* _Was the time-decay scoring tuned correctly?_\n")
    buf.write("\n")
