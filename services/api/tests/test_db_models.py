"""DB model tests using in-memory SQLite.

These tests verify:
1. Tables can be created with our metadata.
2. Foreign keys and indexes are registered (via SQL inspection).
3. Basic round-trip: insert a Scenario, link a Run, insert Assets, query back.
4. Cascade behaviour: deleting a Run deletes its Assets.
5. Enum members have the expected string values.
6. duration_sec property on Run.
7. Unique constraints and FK actions work as declared.
"""
from __future__ import annotations

import asyncio
import enum
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.models import (
    Asset,
    AssetStatus,
    AuditAction,
    AuditLog,
    Run,
    RunStatus,
    Scenario,
)


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def engine():
    """Fresh in-memory SQLite for every test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    # SQLite ignores foreign-key constraints by default — turn them on.
    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


# --- helpers ----------------------------------------------------------------


def _scenario(name: str = "test-scenario") -> Scenario:
    return Scenario(
        name=name,
        title="Test",
        version=1,
        difficulty="beginner",
        duration_min=30,
        tags=["x"],
        spec={"apiVersion": "divide/v1", "kind": "Scenario"},
        authors=[{"handle": "tester"}],
        source_path="examples/scenarios/test.scenario.yaml",
    )


# --- metadata ---------------------------------------------------------------


def test_all_tables_present() -> None:
    tables = set(Base.metadata.tables)
    assert {"scenarios", "runs", "assets", "audit_log"} <= tables


def test_naming_convention_applied() -> None:
    # Check directly via table constraints (no DB needed).
    # Every constraint in our convention gets a `uq_`, `pk_`, `fk_`, or `ck_` prefix.
    for tbl_name in ("scenarios", "runs", "assets", "audit_log"):
        tbl = Base.metadata.tables[tbl_name]
        for c in tbl.constraints:
            if hasattr(c, "name") and c.name:
                assert c.name.startswith(("uq_", "pk_", "fk_", "ck_")), (
                    f"{tbl_name}: unexpected constraint name {c.name!r}"
                )


def test_required_indexes_present() -> None:
    for tbl_name in ("scenarios", "runs", "assets", "audit_log"):
        tbl = Base.metadata.tables[tbl_name]
        assert len(tbl.indexes) >= 1, f"no indexes declared on {tbl_name}"


# --- enums ------------------------------------------------------------------


def test_run_status_enum_members() -> None:
    assert {s.value for s in RunStatus} == {
        "pending", "running", "succeeded", "failed", "timeout", "cancelled",
    }


def test_asset_status_enum_members() -> None:
    assert {s.value for s in AssetStatus} == {
        "planned", "cloning", "booting", "running",
        "stopping", "stopped", "failed", "orphaned",
    }


def test_audit_action_enum_members() -> None:
    assert AuditAction.SCENARIO_CREATED.value == "scenario.created"
    assert AuditAction.RUN_STARTED.value == "run.started"


# --- round-trip -------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_round_trip(session: AsyncSession) -> None:
    """Insert scenario -> run -> 2 assets -> audit, read back."""
    scenario = _scenario("phish-to-ransom")
    session.add(scenario)
    await session.flush()

    run = Run(
        scenario_id=scenario.id,
        status=RunStatus.RUNNING,
        started_by="alice",
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    asset_a = Asset(
        run_id=run.id,
        role="red_attacker",
        kind="vm",
        template="tpl-kali-cloudinit",
        status=AssetStatus.RUNNING,
        pve_vmid=9001,
        pve_node="pve",
    )
    asset_b = Asset(
        run_id=run.id,
        role="dc_server",
        kind="vm",
        template="tpl-win2022-dc",
        status=AssetStatus.RUNNING,
        pve_vmid=9002,
    )
    session.add_all([asset_a, asset_b])
    session.add(AuditLog(action=AuditAction.RUN_STARTED, actor="alice", run_id=run.id))
    session.add(AuditLog(action=AuditAction.ASSET_SPAWNED, run_id=run.id, asset_id=asset_a.id))
    await session.commit()

    # Re-query
    got = (await session.execute(select(Scenario).where(Scenario.name == "phish-to-ransom"))).scalar_one()
    assert got.id == scenario.id
    assert got.title == "Test"
    assert got.spec["kind"] == "Scenario"

    runs = (await session.execute(select(Run).where(Run.scenario_id == scenario.id))).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == RunStatus.RUNNING
    assert runs[0].started_by == "alice"
    assert runs[0].duration_sec is None  # not ended yet

    assets = (await session.execute(select(Asset).where(Asset.run_id == run.id).order_by(Asset.role))).scalars().all()
    assert len(assets) == 2
    assert [a.role for a in assets] == ["dc_server", "red_attacker"]
    assert assets[0].pve_vmid == 9002  # dc_server's VMID


@pytest.mark.asyncio
async def test_run_duration_sec_after_end(session: AsyncSession) -> None:
    scenario = _scenario()
    session.add(scenario)
    await session.flush()

    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 12, 5, 30, tzinfo=timezone.utc)
    run = Run(
        scenario_id=scenario.id,
        status=RunStatus.SUCCEEDED,
        started_at=start,
        ended_at=end,
    )
    session.add(run)
    await session.commit()

    got = (await session.execute(select(Run))).scalar_one()
    assert got.duration_sec == 330  # 5m30s


@pytest.mark.asyncio
async def test_unique_asset_role_per_run(session: AsyncSession) -> None:
    """F3 follow-up lifts the (run_id, role) unique constraint so
    ``count: N`` assets can spawn N clones with suffixed role names.
    Two rows with the same exact (run_id, role) are now allowed.

    See migration 0004_asset_instance.py.
    """
    scenario = _scenario()
    session.add(scenario)
    await session.flush()
    run = Run(scenario_id=scenario.id, status=RunStatus.PENDING)
    session.add(run)
    await session.flush()

    session.add(Asset(run_id=run.id, role="red_attacker", template="t1"))
    session.add(Asset(run_id=run.id, role="red_attacker", template="t2"))
    await session.commit()  # both succeed; (run_id, role) no longer unique


@pytest.mark.asyncio
async def test_unique_scenario_name(session: AsyncSession) -> None:
    session.add(_scenario("dup"))
    await session.commit()
    session.add(_scenario("dup"))
    with pytest.raises(Exception):
        await session.commit()


@pytest.mark.asyncio
async def test_cascade_delete_assets(session: AsyncSession) -> None:
    """Deleting a Run cascades to its Assets, but NOT to the Scenario."""
    scenario = _scenario()
    session.add(scenario)
    await session.flush()
    run = Run(scenario_id=scenario.id)
    session.add(run)
    await session.flush()
    session.add(Asset(run_id=run.id, role="r", template="t"))
    await session.commit()

    await session.delete(run)
    await session.commit()

    remaining = (await session.execute(select(Asset))).scalars().all()
    assert remaining == []
    still_scenario = (await session.execute(select(Scenario))).scalar_one()
    assert still_scenario.id == scenario.id


@pytest.mark.asyncio
async def test_audit_log_foreign_keys_null_on_delete(session: AsyncSession) -> None:
    """AuditLog.run_id is ON DELETE SET NULL — survives Run removal."""
    scenario = _scenario()
    session.add(scenario)
    await session.flush()
    run = Run(scenario_id=scenario.id)
    session.add(run)
    await session.flush()
    session.add(AuditLog(action=AuditAction.RUN_STARTED, run_id=run.id))
    await session.commit()

    await session.delete(run)
    await session.commit()

    logs = (await session.execute(select(AuditLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].run_id is None  # SET NULL worked


@pytest.mark.asyncio
async def test_scenario_spec_is_json_blob(session: AsyncSession) -> None:
    """Spec survives round-trip with nested structure intact."""
    spec = {
        "apiVersion": "divide/v1",
        "kind": "Scenario",
        "metadata": {"name": "x", "title": "y", "version": 1,
                     "difficulty": "intermediate", "duration_min": 60},
        "spec": {
            "objectives": {"red": ["do x"], "blue": ["spot x"]},
            "assets": [{"role": "r", "kind": "vm", "template": "t", "networks": ["n"]}],
            "networks": [{"name": "n", "cidr": "10.0.0.0/24"}],
            "telemetry": {"sinks": [{"type": "stdout"}]},
            "scoring": {
                "blue": {"rules": [{"id": "b", "weight": 100}], "pass_threshold": 70},
                "red": {"rules": [{"id": "r", "weight": 100}], "pass_threshold": 50},
            },
            "win_conditions": {"red": ["x"], "blue": ["y"]},
            "artifacts": {"sink_to": "minio", "retention_days": 7},
        },
    }
    s = _scenario()
    s.spec = spec
    s.tags = ["ransomware", "phishing", "ransomware"]  # dupes; we don't constrain
    session.add(s)
    await session.commit()

    got = (await session.execute(select(Scenario))).scalar_one()
    assert got.spec["spec"]["networks"][0]["cidr"] == "10.0.0.0/24"
    assert got.tags == ["ransomware", "phishing", "ransomware"]


@pytest.mark.asyncio
async def test_relationship_assets_loaded_via_selectin(session: AsyncSession) -> None:
    scenario = _scenario()
    session.add(scenario)
    await session.flush()
    run = Run(scenario_id=scenario.id)
    session.add(run)
    await session.flush()
    session.add(Asset(run_id=run.id, role="r1", template="t1"))
    session.add(Asset(run_id=run.id, role="r2", template="t2"))
    await session.commit()

    from sqlalchemy.orm import selectinload

    got_r = (
        await session.execute(
            select(Run).options(selectinload(Run.assets)).order_by(Run.id)
        )
    ).scalars().first()
    assert got_r is not None
    assert len(got_r.assets) == 2
    roles = sorted(a.role for a in got_r.assets)
    assert roles == ["r1", "r2"]


@pytest.mark.asyncio
async def test_status_transitions_persist(session: AsyncSession) -> None:
    scenario = _scenario()
    session.add(scenario)
    await session.flush()
    run = Run(scenario_id=scenario.id, status=RunStatus.PENDING)
    session.add(run)
    await session.commit()

    for new_status in [RunStatus.RUNNING, RunStatus.SUCCEEDED]:
        run.status = new_status
        await session.commit()
        fresh = (await session.execute(select(Run))).scalar_one()
        assert fresh.status == new_status
