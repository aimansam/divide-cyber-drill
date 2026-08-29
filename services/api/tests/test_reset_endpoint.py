"""Q23-B2 + B3: ``POST /drills/{id}/reset`` guards + audit.

Live-run guard (B2): previously the endpoint would silently drop
assets + flip status to PENDING mid-drill. Now returns 409 with
"run id=X is live; stop it first" when the run is in PENDING
or RUNNING.

Audit trail (B3): previously the endpoint wrote no audit row.
Now writes ``run.reset`` (the new AuditAction value shipped
with migration 0017) so "who reset what when" is answerable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.models import (
    AssetStatus,
    AuditAction,
    AuditLog,
    RunStatus,
)


@pytest.fixture
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


@pytest.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        # Stub FK target for Run.
        sc = models.Scenario(
            name="q23-reset",
            title="Q23 reset test",
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
    await engine.dispose()


async def _make_run(
    s: AsyncSession,
    status: RunStatus,
    *,
    template_id: int | None = None,
) -> models.Run:
    run = models.Run(
        scenario_id=1, started_by="q23-test", status=status
    )
    if template_id is not None:
        run.template_id = template_id
    s.add(run)
    await s.commit()
    return run


@pytest.mark.asyncio
async def test_reset_returns_409_for_running_run(session):
    """Q23-B2: live runs cannot be reset."""
    run = await _make_run(session, RunStatus.RUNNING, template_id=99)
    # Build a minimal template so we can isolate the live-run
    # guard from the missing-template guard.
    tpl = models.Template(
        name=f"tpl-q23-{run.id}",
        title="Q23 reset template",
        description="",
        scenario_id=1,
        snapshot={"assets": []},
        created_by="q23-test",
    )
    s_add = models.Template
    s = session
    s.add(tpl)
    await s.commit()
    run.template_id = tpl.id
    await s.commit()

    # Import here so we get the in-memory DB session state.
    from app.routers.drills import reset_run

    class _FakeToken:
        sub = "q23-actor"
        role = "admin"

    with pytest.raises(Exception) as exc_info:
        await reset_run(
            run_id=run.id,
            session=session,
            token=_FakeToken(),
        )
    # We expect a 409 with the live-run detail.
    assert exc_info.value.status_code == 409
    assert "is live" in str(exc_info.value.detail)
    assert "stop it first" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_reset_returns_409_for_pending_run(session):
    """Pending runs (bootstrapped but not yet started) also rejected."""
    run = await _make_run(session, RunStatus.PENDING, template_id=99)
    tpl = models.Template(
        name=f"tpl-q23-{run.id}-p",
        title="Q23 reset template",
        description="",
        scenario_id=1,
        snapshot={"assets": []},
        created_by="q23-test",
    )
    session.add(tpl)
    await session.commit()
    run.template_id = tpl.id
    await session.commit()

    from app.routers.drills import reset_run

    class _FakeToken:
        sub = "q23"
        role = "admin"

    with pytest.raises(Exception) as exc_info:
        await reset_run(
            run_id=run.id,
            session=session,
            token=_FakeToken(),
        )
    assert exc_info.value.status_code == 409
    assert "is live" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_reset_writes_audit_row_on_success(session):
    """Q23-B3: a successful reset now writes a run.reset audit row."""
    # Build a terminal run + template with one asset.
    run = await _make_run(session, RunStatus.SUCCEEDED)
    tpl = models.Template(
        name=f"tpl-q23-{run.id}-ok",
        title="Q23 reset template",
        description="",
        scenario_id=1,
        snapshot={
            "assets": [
                {"role": "drill_vm", "kind": "vm", "template": "tpl-x"}
            ]
        },
        created_by="q23-test",
    )
    session.add(tpl)
    await session.commit()
    run.template_id = tpl.id
    await session.commit()

    from app.routers.drills import reset_run

    class _FakeToken:
        sub = "q23-actor"
        role = "admin"

    out = await reset_run(
        run_id=run.id,
        session=session,
        token=_FakeToken(),
    )
    assert out["status"] == "pending"
    assert out["asset_count"] == 1
    assert out["reset_by"] == "q23-actor"

    audit = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == AuditAction.RUN_RESET,
                AuditLog.run_id == run.id,
            )
        )
    ).scalars().all()
    assert len(audit) == 1
    row = audit[0]
    assert row.actor == "q23-actor"
    assert row.details["asset_count"] == 1
    assert row.details["template_id"] == tpl.id
    # Reset flips status to PENDING + wipes started_at/ended_at.
    await session.refresh(run)
    assert run.status == RunStatus.PENDING


@pytest.mark.asyncio
async def test_reset_returns_409_for_missing_template(session):
    """The pre-existing template-less guard still works."""
    run = await _make_run(session, RunStatus.SUCCEEDED)
    # template_id stays None.
    from app.routers.drills import reset_run

    class _FakeToken:
        sub = "q23"
        role = "admin"

    with pytest.raises(Exception) as exc_info:
        await reset_run(
            run_id=run.id,
            session=session,
            token=_FakeToken(),
        )
    assert exc_info.value.status_code == 409
    assert "save-as-template" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stop_on_already_terminal_run_is_noop(session):
    """Q23-B1: stopping an already-terminal run does not write
    another RUN_STOPPED audit row. Pre-B1, double-clicking Stop
    stacked audit rows.
    """
    run = await _make_run(session, RunStatus.SUCCEEDED)
    asset = models.Asset(
        run_id=run.id,
        role="drill_vm",
        kind="vm",
        template="tpl-x",
        status=AssetStatus.STOPPED,
        pve_vmid=None,
        pve_node=None,
    )
    session.add(asset)
    await session.commit()

    from app.runners.runner import Runner
    from app.runners.mock_adapter import MockProxmoxAdapter

    runner = Runner(adapter=MockProxmoxAdapter())
    out = await runner.stop_run(
        run.id,
        reason="double-click",
        actor="q23",
        session=session,
    )
    assert out.status == RunStatus.SUCCEEDED

    audit = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == AuditAction.RUN_STOPPED,
                AuditLog.run_id == run.id,
            )
        )
    ).scalars().all()
    # The guard short-circuits before writing any audit row.
    assert audit == []
