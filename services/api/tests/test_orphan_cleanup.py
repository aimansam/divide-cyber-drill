"""Q22: orphan-asset janitor (unit tests against in-memory SQLite).

The two service functions (``list_orphans`` + ``cleanup_orphans``)
are exercised directly with a mock adapter. HTTP-layer RBAC +
JSON-shape checks live in ``test_admin_router.py`` and were
covered by live curl in the Q22 deployment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.services import orphan_cleanup as svc


@pytest.fixture
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


@pytest.fixture
async def session(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        # Scenario FK is required for Run inserts; create a stub.
        sc = models.Scenario(
            name="q22-stub",
            title="Q22 test stub",
            version=1,
            difficulty="smoke",
            duration_min=5,
            spec={"apiVersion": "divide/v1", "kind": "Scenario", "spec": {"assets": []}},
        )
        s.add(sc)
        await s.commit()
        yield s
        await s.rollback()
    await engine.dispose()


async def _mk_orphan(
    s: AsyncSession,
    vmid: int,
    *,
    status=models.AssetStatus.ORPHANED,
    run_status=models.RunStatus.SUCCEEDED,
    pve_vmid: int | None = None,
    pve_node: str | None = "pve",
    age_seconds: int = 600,
) -> models.Asset:
    run = models.Run(scenario_id=1, started_by="q22", status=run_status)
    s.add(run)
    await s.flush()
    a = models.Asset(
        run_id=run.id,
        role="drill_vm",
        kind="vm",
        template="tpl-debian-cloudinit",
        status=status,
        pve_vmid=pve_vmid if pve_vmid is not None else vmid,
        pve_node=pve_node,
        error="teardown failed",
    )
    s.add(a)
    await s.flush()
    ancient = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    a.created_at = ancient
    a.updated_at = ancient
    await s.commit()
    return a
    return a


def _fake_adapter() -> MagicMock:
    a = MagicMock()
    a.stop_vm = AsyncMock(return_value=None)
    a.destroy_vm = AsyncMock(return_value=None)
    return a


@pytest.mark.asyncio
async def test_list_orphans_returns_old_enough(session):
    await _mk_orphan(session, 9001, age_seconds=600)
    await _mk_orphan(session, 9002, age_seconds=30)  # too young
    out = await svc.list_orphans(session, grace_minutes=5)
    vmids = [c.pve_vmid for c in out]
    assert 9001 in vmids
    assert 9002 not in vmids


@pytest.mark.asyncio
async def test_list_orphans_skips_live_runs(session):
    await _mk_orphan(
        session, 9003, run_status=models.RunStatus.RUNNING, age_seconds=600
    )
    out = await svc.list_orphans(session, grace_minutes=0)
    vmids = [c.pve_vmid for c in out]
    assert 9003 not in vmids


@pytest.mark.asyncio
async def test_list_orphans_skips_missing_vmid(session):
    """An orphan without a pve_vmid can't be cleaned on PVE.

    Call the Asset ctor directly (bypass the helper) so we can
    leave pve_vmid explicitly None without the vmid-fallback
    filling it in.
    """
    run = models.Run(
        scenario_id=1, started_by="q22", status=models.RunStatus.SUCCEEDED
    )
    session.add(run)
    await session.flush()
    a = models.Asset(
        run_id=run.id,
        role="drill_vm",
        kind="vm",
        template="tpl-debian-cloudinit",
        status=models.AssetStatus.ORPHANED,
        pve_vmid=None,
        pve_node="pve",
        error="clone failed at allocate",
    )
    session.add(a)
    await session.flush()
    ancient = datetime.now(timezone.utc) - timedelta(seconds=600)
    a.created_at = ancient
    a.updated_at = ancient
    await session.commit()
    out = await svc.list_orphans(session, grace_minutes=0)
    assert out == []


@pytest.mark.asyncio
async def test_cleanup_orphans_flips_status_and_audits(session):
    a = await _mk_orphan(session, 9010, age_seconds=600)
    adapter = _fake_adapter()
    result = await svc.cleanup_orphans(
        session, adapter, "q22-actor", grace_minutes=0
    )
    assert result.scanned == 1
    assert result.destroyed == 1
    assert result.failed == []

    await session.refresh(a)
    assert a.status == models.AssetStatus.STOPPED
    assert a.error is None
    assert a.cleaned_at is not None

    audit = (await session.execute(
        select(models.AuditLog).where(
            models.AuditLog.action == models.AuditAction.ASSET_CLEANED
        )
    )).scalars().all()
    assert len(audit) == 1
    row = audit[0]
    assert row.asset_id == a.id
    assert row.actor == "q22-actor"
    assert row.details["vmid"] == 9010
    assert row.details["node"] == "pve"
    assert row.details["previous_error"] == "teardown failed"


@pytest.mark.asyncio
async def test_cleanup_orphans_records_failure_and_keeps_status(session):
    a = await _mk_orphan(session, 9011, age_seconds=600)
    adapter = MagicMock()
    adapter.stop_vm = AsyncMock(return_value=None)
    adapter.destroy_vm = AsyncMock(side_effect=RuntimeError("PVE down"))
    result = await svc.cleanup_orphans(
        session, adapter, "q22", grace_minutes=0
    )
    assert result.scanned == 1
    assert result.destroyed == 0
    assert len(result.failed) == 1
    assert result.failed[0].asset_id == a.id
    assert "PVE down" in result.failed[0].error

    await session.refresh(a)
    assert a.status == models.AssetStatus.ORPHANED
    assert a.cleaned_at is None
    assert "cleanup retry failed" in (a.error or "")
    assert "PVE down" in (a.error or "")


@pytest.mark.asyncio
async def test_cleanup_orphans_idempotent(session):
    """Re-running on a freshly-cleaned DB returns scanned=0."""
    await _mk_orphan(session, 9012, age_seconds=600)
    adapter = _fake_adapter()
    await svc.cleanup_orphans(session, adapter, "q22", grace_minutes=0)
    result = await svc.cleanup_orphans(session, adapter, "q22", grace_minutes=0)
    assert result.scanned == 0
    assert result.destroyed == 0


@pytest.mark.asyncio
async def test_cleanup_orphans_skips_running_run(session):
    """Orphan whose run is still RUNNING is skipped, not destroyed."""
    a = await _mk_orphan(
        session, 9013, run_status=models.RunStatus.RUNNING, age_seconds=600
    )
    adapter = _fake_adapter()
    result = await svc.cleanup_orphans(
        session, adapter, "q22", grace_minutes=0
    )
    assert result.scanned == 0  # list_orphans filtered it out
    assert result.destroyed == 0
    adapter.destroy_vm.assert_not_called()
    await session.refresh(a)
    assert a.status == models.AssetStatus.ORPHANED


@pytest.mark.asyncio
async def test_cleanup_orphans_respects_asset_ids_filter(session):
    """asset_ids=[2] only touches that one."""
    a1 = await _mk_orphan(session, 9100, age_seconds=600)
    a2 = await _mk_orphan(session, 9101, age_seconds=600)
    adapter = _fake_adapter()
    result = await svc.cleanup_orphans(
        session, adapter, "q22", grace_minutes=0, asset_ids=[a2.id]
    )
    assert result.scanned == 1
    assert result.destroyed == 1
    await session.refresh(a1)
    await session.refresh(a2)
    assert a1.status == models.AssetStatus.ORPHANED
    assert a2.status == models.AssetStatus.STOPPED
