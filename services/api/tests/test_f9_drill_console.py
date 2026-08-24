"""F9.1: get_drill must surface exercise_id so the portal DrillConsole
can decide whether to render the multi-team panels (leaderboard +
live SOC stream) inline.

Pre-F9.1, ``GET /api/v1/drills/{id}`` returned the Run row without
``exercise_id``. The portal couldn't tell a single-team Run from a
multi-team Exercise Run, which is what F9.1 fixes on the wire.

This file pins:

  * ``exercise_id`` is null for legacy single-team Runs.
  * ``exercise_id`` is populated for F6 Exercise Runs.
  * The shape is stable across re-requests (idempotent).
  * 404 / 401 still work as before; the new field is additive.

The seed helpers mirror the pattern in
``test_reports.py::_seed_terminal_run`` (Scenario + Run + AuditLog)
plus a minimal Exercise row for the multi-team case.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient


def _now_name(prefix: str) -> str:
    """Unique scenario / exercise name per test invocation."""
    return f"{prefix}-{int(time.time() * 1000) % 100000000}"


def _admin_token(sub: str = "alice") -> str:
    from app.core.auth import Role, sign_token
    return sign_token(sub, Role.ADMIN.value, 3600)


def _run_async(coro):
    """Run an async helper to completion, return its result.

    The seed helpers here are simpler as plain async functions;
    this shim wraps them so the test functions stay sync (matching
    the FastAPI TestClient style in test_reports.py).

    Why not ``asyncio.run(coro)``?
        pytest-asyncio installs an event loop in the main thread
        for the test session. Calling ``asyncio.run`` raises
        "There is no current event loop" because the policy has
        already been bound. We install a fresh loop locally
        instead.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _clean_db_after():
    """Truncate DB tables after each F9 test.

    Other test files in this suite (test_routers.py in particular)
    assume an EMPTY database. Our seed helpers leave rows behind;
    this autouse teardown is the cheapest way to keep both passing.

    Mirrors the pattern in ``test_reports.py::_clean_db_after``.
    """
    from sqlalchemy import delete

    from app.db import models as db_models
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    yield  # test runs first

    async def _cleanup():
        async with sm() as s:
            # F9 seeds Exercises too; clear before the cascading tables.
            await s.execute(delete(db_models.TeamMembership))
            await s.execute(delete(db_models.Team))
            await s.execute(delete(db_models.Exercise))
            await s.execute(delete(db_models.AuditLog))
            await s.execute(delete(db_models.Asset))
            await s.execute(delete(db_models.Run))
            await s.execute(delete(db_models.Scenario))
            await s.commit()

    # Same event-loop isolation as the seed helpers -- pytest-asyncio
    # owns the main-thread loop, so we run cleanup on a fresh loop.
    import asyncio as _asyncio

    loop = _asyncio.new_event_loop()
    try:
        loop.run_until_complete(_cleanup())
    except Exception:  # noqa: BLE001 -- best-effort
        pass
    finally:
        loop.close()


async def _seed_single_team_run() -> tuple[int, int]:
    """Seed a scenario + Run with no Exercise binding. Returns (run_id, scenario_id)."""
    from datetime import datetime, timezone

    from app.db import models as db_models
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    name = _now_name("f9-single")
    async with sm() as session:
        s = db_models.Scenario(
            name=name,
            title="F9 Single-Team",
            version=1,
            difficulty="smoke",
            duration_min=5,
            tags=[],
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "metadata": {"name": name, "title": "F9 Single-Team", "version": 1},
                "spec": {
                    "objectives": {"red": ["x"], "blue": ["y"]},
                    "assets": [{"role": "drill_vm", "kind": "vm", "template": "tpl-x"}],
                },
            },
        )
        session.add(s)
        await session.flush()
        run = db_models.Run(
            scenario_id=s.id,
            status=db_models.RunStatus.SUCCEEDED,
            started_by="alice",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        await session.commit()
        return run.id, s.id


async def _seed_multi_team_run() -> tuple[int, int, int]:
    """Seed an Exercise + Run bound to it. Returns (run_id, scenario_id, exercise_id)."""
    from datetime import datetime, timezone

    from app.db import models as db_models
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    name = _now_name("f9-multi")
    async with sm() as session:
        s = db_models.Scenario(
            name=name,
            title="F9 Multi-Team",
            version=1,
            difficulty="smoke",
            duration_min=5,
            tags=[],
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "metadata": {"name": name, "title": "F9 Multi-Team", "version": 1},
                "spec": {
                    "objectives": {"red": ["x"], "blue": ["y"]},
                    "assets": [{"role": "drill_vm", "kind": "vm", "template": "tpl-x"}],
                },
            },
        )
        session.add(s)
        await session.flush()
        ex = db_models.Exercise(
            name=name,
            title="F9 Multi-Team",
            scenario_id=s.id,
            status=db_models.ExerciseStatus.LIVE,
            starts_at=datetime.now(timezone.utc),
            created_by="alice",
        )
        session.add(ex)
        await session.flush()
        run = db_models.Run(
            scenario_id=s.id,
            exercise_id=ex.id,
            status=db_models.RunStatus.RUNNING,
            started_by="alice",
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        await session.commit()
        return run.id, s.id, ex.id


def test_get_drill_returns_null_exercise_id_for_single_team(client):
    """Single-team Runs (no Exercise) expose exercise_id === null."""
    run_id, _scenario_id = _run_async(_seed_single_team_run())

    r = client.get(
        f"/api/v1/drills/{run_id}",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.json()
    # F9.1: the field exists and is null for legacy runs.
    assert "exercise_id" in body
    assert body["exercise_id"] is None
    # shape sanity
    assert body["run_id"] == run_id
    assert body["status"] == "succeeded"


def test_get_drill_returns_exercise_id_for_multi_team(client):
    """F6 Exercise Runs expose the bound exercise_id so the portal
    can render leaderboard + live SOC inline."""
    run_id, _scenario_id, exercise_id = _run_async(_seed_multi_team_run())

    r = client.get(
        f"/api/v1/drills/{run_id}",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exercise_id"] == exercise_id
    assert body["run_id"] == run_id
    assert body["status"] == "running"


def test_get_drill_exercise_id_is_idempotent(client):
    """Repeated GETs return the same exercise_id (no caching surprises)."""
    run_id, _scenario_id, exercise_id = _run_async(_seed_multi_team_run())

    headers = {"X-Divide-Token": _admin_token()}
    r1 = client.get(f"/api/v1/drills/{run_id}", headers=headers)
    r2 = client.get(f"/api/v1/drills/{run_id}", headers=headers)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["exercise_id"] == r2.json()["exercise_id"] == exercise_id


def test_get_drill_unknown_run_returns_404(client):
    """Regression: 404 still works; the new field didn't break the path."""
    r = client.get(
        "/api/v1/drills/9999999",
        headers={"X-Divide-Token": _admin_token()},
    )
    assert r.status_code == 404


def test_get_drill_anonymous_returns_401(client):
    """Regression: 401 gate still fires; the new field doesn't bypass auth."""
    r = client.get("/api/v1/drills/1")
    assert r.status_code == 401
