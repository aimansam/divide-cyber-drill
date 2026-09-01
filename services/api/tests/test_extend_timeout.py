from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.models import AuditAction, AuditLog, RunStatus
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunnerError


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        sc = models.Scenario(
            name="extend-timeout-test",
            title="Extend Timeout Test",
            version=1,
            difficulty="smoke",
            duration_min=5,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {"assets": []},
            },
        )
        s.add(sc)
        await s.commit()
        yield s
        await s.rollback()


@pytest.mark.asyncio
async def test_runner_extend_timeout_happy_path(session: AsyncSession):
    scen = (await session.execute(select(models.Scenario))).scalar_one()
    run = models.Run(
        scenario_id=scen.id,
        status=RunStatus.RUNNING,
        started_by="alice",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.commit()

    runner = Runner(adapter=MockProxmoxAdapter())
    
    # Pre-set deadline
    Runner._active_deadlines[run.id] = datetime.now(timezone.utc) + timedelta(minutes=10)

    res = await runner.extend_timeout(
        run_id=run.id,
        extend_min=30,
        actor="alice",
        session=session,
    )

    assert res["run_id"] == run.id
    assert res["extended_by_min"] == 30
    assert res["remaining_sec"] > 2300  # around 40 mins (2400s)

    # Check AuditLog
    audits = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.run_id == run.id,
                AuditLog.action == AuditAction.RUN_EXTENDED,
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].actor == "alice"
    assert audits[0].details["extended_by_min"] == 30

    # Check get_timeout_sec classmethod
    remaining = Runner.get_timeout_sec(run.id)
    assert remaining is not None
    assert remaining > 0


@pytest.mark.asyncio
async def test_runner_extend_timeout_terminal_raises(session: AsyncSession):
    scen = (await session.execute(select(models.Scenario))).scalar_one()
    run = models.Run(
        scenario_id=scen.id,
        status=RunStatus.SUCCEEDED,
        started_by="alice",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.commit()

    runner = Runner(adapter=MockProxmoxAdapter())
    with pytest.raises(RunnerError, match="cannot extend timeout for terminal run"):
        await runner.extend_timeout(
            run_id=run.id,
            extend_min=30,
            actor="alice",
            session=session,
        )


@pytest.mark.asyncio
async def test_runner_extend_timeout_invalid_mins(session: AsyncSession):
    runner = Runner(adapter=MockProxmoxAdapter())
    with pytest.raises(RunnerError, match="extend_min must be between 1 and 240"):
        await runner.extend_timeout(
            run_id=999,
            extend_min=0,
            session=session,
        )
