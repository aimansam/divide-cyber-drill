"""Tests for the drill auto-timeout watchdog (L2 2.8).

The watchdog is a fire-and-forget asyncio task spawned by
``Runner._schedule_watchdog`` after a run enters RUNNING. After
``drill_timeout_min`` minutes, it checks if the run is still
RUNNING and, if so, flips it to TIMEOUT, best-effort tears down
assets, and writes a RUN_TIMEOUT audit.

We test by driving ``Runner._watchdog_timeout_fire`` directly with
tiny timeouts — bypassing ``_schedule_watchdog`` so we don't have to
manage a live event loop in pytest.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import models as db_models
from app.db.session import get_sessionmaker


@pytest.fixture
def seed_one_run():
    """Seed one scenario + run. Each call gets a UNIQUE scenario name
    so multiple invocations don't collide on the scenarios.name unique
    constraint (which IS the schema's intent — same scenario cannot
    be inserted twice under the same name).
    """
    import time

    name = f"watchdog-test-{int(time.time() * 1000) % 100000000}"

    async def _go():
        sm = get_sessionmaker()
        async with sm() as session:
            s = db_models.Scenario(
                name=name,
                title="Watchdog Test",
                version=1,
                difficulty="smoke",
                duration_min=5,
                tags=[],
                spec={
                    "apiVersion": "divide/v1",
                    "kind": "Scenario",
                    "metadata": {
                        "name": name,
                        "title": "Watchdog Test",
                        "version": 1,
                        "difficulty": "smoke",
                        "duration_min": 5,
                        "tags": [],
                    },
                    "spec": {
                        "objectives": {"red": ["x"], "blue": ["y"]},
                        "assets": [
                            {"role": "drill_vm", "kind": "vm", "template": "tpl-x"}
                        ],
                    },
                },
            )
            session.add(s)
            await session.flush()
            r = db_models.Run(
                scenario_id=s.id,
                status=db_models.RunStatus.RUNNING,
                started_by="alice",
                started_at=datetime.now(timezone.utc),
            )
            session.add(r)
            await session.flush()
            run_id = r.id
            await session.commit()
            return run_id

    return asyncio.run(_go())


@pytest.fixture
def runner():
    """A Runner bound to the mock adapter (no PVE needed)."""
    from app.runners.mock_adapter import MockProxmoxAdapter
    from app.runners.runner import Runner

    return Runner(adapter=MockProxmoxAdapter())


def test_watchdog_flips_running_to_timeout_after_deadline(runner, seed_one_run):
    """Watchdog fires for a RUNNING run past the timeout window.

    Tiny 0.05-min timeout (3 s) so the test runs fast.
    """
    async def _go():
        await runner._watchdog_timeout_fire(
            run_id=seed_one_run,
            node="pve",
            timeout_min=0.05,
            asset_count=1,
        )
        sm = get_sessionmaker()
        async with sm() as s:
            row = (
                await s.execute(
                    select(db_models.Run).where(
                        db_models.Run.id == seed_one_run
                    )
                )
            ).scalar_one()
            return row.status, row.error

    status, error = asyncio.run(_go())
    assert status.value == "timeout"
    assert "auto-timeout" in (error or "")


def test_watchdog_no_op_when_run_already_terminal(runner, seed_one_run):
    """If a run cancelled/completed before the deadline, the watchdog
    is a no-op — it logs and returns.
    """
    async def _go():
        # Mark the run CANCELLED first.
        sm = get_sessionmaker()
        async with sm() as s:
            row = (
                await s.execute(
                    select(db_models.Run).where(
                        db_models.Run.id == seed_one_run
                    )
                )
            ).scalar_one()
            row.status = db_models.RunStatus.CANCELLED
            row.ended_at = datetime.now(timezone.utc)
            await s.commit()

        # Fire the watchdog — must not flip anything.
        await runner._watchdog_timeout_fire(
            run_id=seed_one_run,
            node="pve",
            timeout_min=0.05,
            asset_count=1,
        )

        async with sm() as s:
            row = (
                await s.execute(
                    select(db_models.Run).where(
                        db_models.Run.id == seed_one_run
                    )
                )
            ).scalar_one()
            return row.status, row.error

    status, _ = asyncio.run(_go())
    assert status.value == "cancelled"


def test_watchdog_writes_run_timeout_audit(runner, seed_one_run):
    """Watchdog writes an audit row with action=RUN_TIMEOUT, actor=watchdog."""
    async def _go():
        await runner._watchdog_timeout_fire(
            run_id=seed_one_run,
            node="pve",
            timeout_min=0.05,
            asset_count=1,
        )
        sm = get_sessionmaker()
        async with sm() as s:
            rows = (
                await s.execute(
                    select(db_models.AuditLog)
                    .where(db_models.AuditLog.run_id == seed_one_run)
                    .where(
                        db_models.AuditLog.action
                        == db_models.AuditAction.RUN_TIMEOUT
                    )
                )
            ).scalars().all()
            return rows

    rows = asyncio.run(_go())
    assert len(rows) >= 1
    assert rows[0].actor == "watchdog"
    assert rows[0].details["timeout_min"] == pytest.approx(0.05, abs=0.01)


def test_watchdog_disabled_does_not_schedule(monkeypatch):
    """drill_timeout_enabled=False → no task scheduled."""
    invocations = []

    async def _spy(*args, **kwargs):
        invocations.append(kwargs.get("run_id"))

    from app.core.config import settings
    from app.runners.mock_adapter import MockProxmoxAdapter
    from app.runners.runner import Runner

    monkeypatch.setattr(settings, "drill_timeout_enabled", False, raising=False)
    runner = Runner(adapter=MockProxmoxAdapter())
    runner._watchdog_timeout_fire = _spy  # type: ignore[assignment]
    runner._schedule_watchdog(run_id=999, node="pve", asset_count=0)
    assert invocations == []


def test_watchdog_zero_min_skipped(monkeypatch):
    """drill_timeout_min=0 → no task scheduled."""
    invocations = []

    async def _spy(*args, **kwargs):
        invocations.append(kwargs.get("run_id"))

    from app.core.config import settings
    from app.runners.mock_adapter import MockProxmoxAdapter
    from app.runners.runner import Runner

    monkeypatch.setattr(settings, "drill_timeout_min", 0, raising=False)
    runner = Runner(adapter=MockProxmoxAdapter())
    runner._watchdog_timeout_fire = _spy  # type: ignore[assignment]
    runner._schedule_watchdog(run_id=999, node="pve", asset_count=0)
    assert invocations == []