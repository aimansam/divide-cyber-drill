"""F11: drill debrief artifact endpoint.

These tests pin the contract:

  * 200 + markdown body for a terminal run.
  * 404 for an unknown run id.
  * 401 for anonymous.
  * 403 for a red/blue token that can't see the run.
  * 409 for a non-terminal run.
  * Content-Type header is text/markdown.
  * Markdown sections are present in the right order.
  * Per-flag timing renders each capture as a row.
  * Per-team score reflects Run.score_red / Run.score_blue.
  * Pivot timeline includes run.started + asset.running events.
  * Lessons learned placeholder renders.

We reuse the seed helper from ``test_reports.py`` (terminal run +
audit + asset). On top of that we add flag_submissions +
telemetry_events rows so the rendered markdown has data to show.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.auth import sign_token
from app.db import models as db_models
from app.db.session import get_sessionmaker


def _now_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000) % 100000000}"


def _admin_token(sub: str = "alice") -> str:
    return sign_token(sub, "admin", 3600)


def _red_token(sub: str = "red-1") -> str:
    return sign_token(sub, "red", 3600)


def _run_async(coro):
    """Run an async helper. Mirrors test_f9_drill_console's helper.

    pytest-asyncio owns the main-thread loop, so we use a fresh
    local loop to avoid ``asyncio.run`` policy collisions.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _clean_db_after():
    """Truncate DB tables after each F11 test.

    Same pattern as ``test_f9_drill_console.py`` -- seeds leave
    rows behind; subsequent tests in other files assume EMPTY DB.
    """
    sm = get_sessionmaker()
    yield

    async def _cleanup():
        async with sm() as s:
            await s.execute(delete(db_models.TeamMembership))
            await s.execute(delete(db_models.Team))
            await s.execute(delete(db_models.Exercise))
            await s.execute(delete(db_models.TelemetryEvent))
            await s.execute(delete(db_models.FlagSubmission))
            await s.execute(delete(db_models.AuditLog))
            await s.execute(delete(db_models.Asset))
            await s.execute(delete(db_models.Run))
            await s.execute(delete(db_models.Scenario))
            await s.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_cleanup())
    except Exception:  # noqa: BLE001 -- best-effort
        pass
    finally:
        loop.close()


async def _seed_terminal_run_with_events(
    *, started_by: str = "alice"
) -> tuple[int, int]:
    """Seed a terminal run with assets + flag submissions +
    telemetry events. Returns (run_id, scenario_id)."""
    sm = get_sessionmaker()
    name = _now_name("f11-debrief")
    now = datetime.now(timezone.utc)
    async with sm() as session:
        s = db_models.Scenario(
            name=name,
            title="F11 Debrief Test",
            version=1,
            difficulty="smoke",
            duration_min=5,
            tags=[],
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "metadata": {"name": name, "title": "F11 Debrief Test", "version": 1},
                "spec": {
                    "objectives": {"red": ["x"], "blue": ["y"]},
                    "assets": [
                        {"role": "attacker", "kind": "vm", "template": "tpl-kali"},
                        {"role": "victim", "kind": "vm", "template": "tpl-debian"},
                    ],
                },
            },
        )
        session.add(s)
        await session.flush()
        run = db_models.Run(
            scenario_id=s.id,
            status=db_models.RunStatus.SUCCEEDED,
            started_by=started_by,
            started_at=now,
            ended_at=now,
            score_red=180,
            score_blue=90,
        )
        session.add(run)
        await session.flush()
        # 2 assets
        for role, ip in [("attacker", "10.10.10.5"), ("victim", "10.10.30.10")]:
            session.add(
                db_models.Asset(
                    run_id=run.id,
                    role=role,
                    kind="vm",
                    template=f"tpl-{role}",
                    status=db_models.AssetStatus.RUNNING,
                    pve_vmid=9100 + hash(role) % 100,
                    pve_node="pve",
                    pve_ip=ip,
                )
            )
        # 2 flag submissions (one per team)
        for i, team in enumerate(["red", "blue"]):
            session.add(
                db_models.FlagSubmission(
                    run_id=run.id,
                    flag_id=f"red-flag-{i}",
                    team=team,
                    submitted_by=f"{team}-player-1",
                    captured_at=now,
                    points=100 if team == "red" else 90,
                    elapsed_seconds=120 + i * 60,
                )
            )
        # 4 telemetry events spanning the run lifecycle
        for kind, sev, ts_offset in [
            ("run.started", "info", 0),
            ("asset.running", "info", 30),
            ("flag.captured", "medium", 180),
            ("run.completed", "info", 240),
        ]:
            session.add(
                db_models.TelemetryEvent(
                    run_id=run.id,
                    ts=now.replace(second=ts_offset % 60),
                    source="runner",
                    kind=kind,
                    severity=db_models.TelemetrySeverity(sev),
                    payload={},
                )
            )
        await session.commit()
        return run.id, s.id


# --- happy path ---------------------------------------------------------

def test_get_debrief_returns_markdown(client):
    """Terminal run → 200 with markdown body."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    body = r.text
    # Sections appear in the right order.
    assert "# Drill debrief" in body
    summary_idx = body.find("## Summary")
    score_idx = body.find("## Per-team score")
    flags_idx = body.find("## Per-flag timing")
    pivot_idx = body.find("## Pivot timeline")
    asset_idx = body.find("## Asset table")
    lessons_idx = body.find("## Lessons learned")
    assert -1 < summary_idx < score_idx < flags_idx < pivot_idx < asset_idx < lessons_idx


def test_get_debrief_includes_per_team_scores(client):
    """Score table reflects Run.score_red / score_blue."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.text
    # Seed set score_red=180, score_blue=90.
    assert "| red  |" in body
    assert "| blue |" in body
    assert "| 180 |" in body
    assert "| 90 |" in body
    # Winner callout.
    assert "**Result:** `red` wins." in body


def test_get_debrief_includes_per_flag_rows(client):
    """Each flag submission becomes a row in the timing table."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.text
    # Both seeded flag IDs surface in the table.
    assert "`red-flag-0`" in body
    assert "`red-flag-1`" in body


def test_get_debrief_includes_pivot_timeline(client):
    """Pivot timeline includes run.started + asset.running + flag.captured."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.text
    assert "## Pivot timeline" in body
    assert "`run.started`" in body
    assert "`asset.running`" in body
    assert "`flag.captured`" in body
    assert "`run.completed`" in body


def test_get_debrief_includes_asset_table(client):
    """Asset table lists every asset role + IP."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.text
    assert "## Asset table" in body
    assert "`attacker`" in body
    assert "`victim`" in body
    assert "10.10.10.5" in body
    assert "10.10.30.10" in body


def test_get_debrief_includes_lessons_learned_placeholder(client):
    """The operator-fillable section is always rendered."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.text
    assert "## Lessons learned" in body
    # At least one suggested prompt is rendered.
    assert "Did the red team find any path" in body


def test_get_debrief_content_disposition_inline(client):
    """The Content-Disposition header suggests a sensible filename."""
    run_id, _ = _run_async(_seed_terminal_run_with_events())

    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    assert "run-" in r.headers.get("content-disposition", "")
    assert f"{run_id}-debrief.md" in r.headers["content-disposition"]


# --- failure paths ------------------------------------------------------

def test_get_debrief_unknown_run_returns_404(client):
    r = client.get(
        "/api/v1/drills/9999999/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 404


def test_get_debrief_anonymous_returns_401(client):
    r = client.get("/api/v1/drills/1/debrief.md")
    assert r.status_code == 401


def test_get_debrief_non_terminal_returns_409(client):
    """A pending/running run can't be debriefed."""
    async def _seed_running():
        sm = get_sessionmaker()
        name = _now_name("f11-running")
        async with sm() as session:
            s = db_models.Scenario(
                name=name, title="running", version=1, difficulty="smoke",
                duration_min=5, tags=[],
                spec={
                    "apiVersion": "divide/v1", "kind": "Scenario",
                    "metadata": {"name": name, "title": "running", "version": 1},
                    "spec": {
                        "objectives": {"red": ["x"], "blue": ["y"]},
                        "assets": [{"role": "a", "kind": "vm", "template": "t"}],
                    },
                },
            )
            session.add(s)
            await session.flush()
            run = db_models.Run(
                scenario_id=s.id,
                status=db_models.RunStatus.RUNNING,
                started_by="alice",
            )
            session.add(run)
            await session.commit()
            return run.id
    run_id = _run_async(_seed_running())
    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 409
    assert "non-terminal" in r.text.lower()


def test_get_debrief_red_cannot_see_another_team_run(client):
    """A red player can't peek at a run that isn't theirs.

    Mirror the existing ``test_report_403_red_cannot_see_anothers_run``
    semantics from ``test_reports.py``.
    """
    async def _seed_other_run():
        sm = get_sessionmaker()
        name = _now_name("f11-other")
        async with sm() as session:
            s = db_models.Scenario(
                name=name, title="other", version=1, difficulty="smoke",
                duration_min=5, tags=[],
                spec={
                    "apiVersion": "divide/v1", "kind": "Scenario",
                    "metadata": {"name": name, "title": "other", "version": 1},
                    "spec": {
                        "objectives": {"red": ["x"], "blue": ["y"]},
                        "assets": [{"role": "a", "kind": "vm", "template": "t"}],
                    },
                },
            )
            session.add(s)
            await session.flush()
            run = db_models.Run(
                scenario_id=s.id,
                status=db_models.RunStatus.SUCCEEDED,
                started_by="bob",
            )
            session.add(run)
            await session.commit()
            return run.id
    run_id = _run_async(_seed_other_run())
    r = client.get(
        f"/api/v1/drills/{run_id}/debrief.md",
        headers={"X-Divide-Token": _red_token("red-2")},
    )
    assert r.status_code == 403
