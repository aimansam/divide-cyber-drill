"""Runner unit tests against a MockProxmoxAdapter.

We exercise:
  * Happy path: scenario with N assets -> Run SUCCEEDED, N Assets RUNNING
  * Each asset got cloned, started, and assigned an IP
  * Audit log records the lifecycle
  * Stop tears everything down, marks assets STOPPED
  * Asset-level failure transitions to RUN FAILED + best-effort teardown
  * Scenario with no assets raises
  * Scenario missing in DB raises
  * Missing template raises and Run is marked FAILED
  * Adapter error after some assets are spawned triggers teardown of those
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.models import AssetStatus, AuditAction, RunStatus
from app.runners.adapter import CloneSpec, VmState
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunnerError, RunRequest


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    import asyncio
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


def _scenario_with(name: str, assets_spec: list[dict]) -> models.Scenario:
    return models.Scenario(
        name=name,
        title=name,
        version=1,
        difficulty="beginner",
        duration_min=30,
        spec={
            "apiVersion": "divide/v1",
            "kind": "Scenario",
            "spec": {"assets": assets_spec},
        },
    )


def _asset(role: str, template: str = "tpl-x") -> dict:
    return {"role": role, "kind": "vm", "template": template, "networks": ["n"]}


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_run_creates_run_and_assets(session: AsyncSession) -> None:
    s = _scenario_with(
        "happy",
        [_asset("red_attacker"), _asset("victim_workstation")],
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)

    result = await runner.start_run(
        RunRequest(scenario_id=s.id, started_by="alice"), session
    )
    assert result.status == RunStatus.SUCCEEDED

    runs = (await session.execute(select(models.Run))).scalars().all()
    assert len(runs) == 1
    run = runs[0]
    assert run.status == RunStatus.SUCCEEDED
    assert run.started_by == "alice"
    assert run.started_at is not None
    assert run.ended_at is not None
    assert run.duration_sec is not None and run.duration_sec >= 0

    assets = (await session.execute(select(models.Asset))).scalars().all()
    assert len(assets) == 2
    roles = sorted(a.role for a in assets)
    assert roles == ["red_attacker", "victim_workstation"]
    for a in assets:
        assert a.status == AssetStatus.RUNNING
        assert a.pve_vmid is not None
        assert a.pve_node == "pve"
        assert a.pve_ip is not None


@pytest.mark.asyncio
async def test_start_run_records_audit_log(session: AsyncSession) -> None:
    s = _scenario_with("audited", [_asset("red_attacker")])
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)

    await runner.start_run(
        RunRequest(scenario_id=s.id, started_by="alice"), session
    )

    logs = (await session.execute(select(models.AuditLog))).scalars().all()
    actions = [log.action for log in logs]
    assert AuditAction.RUN_STARTED in actions
    assert AuditAction.ASSET_SPAWNED in actions
    assert AuditAction.RUN_COMPLETED in actions


@pytest.mark.asyncio
async def test_mock_adapter_records_calls(session: AsyncSession) -> None:
    s = _scenario_with("calls", [_asset("red_attacker"), _asset("dc")])
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)

    await runner.start_run(RunRequest(scenario_id=s.id), session)

    # 2 clones, 2 starts, 2 VM-state queries
    assert len(adapter.cloned) == 2
    assert len(adapter.started) == 2
    assert all(spec.name.startswith("divide-") for spec in adapter.cloned)
    # Asset names embed role; check both roles show up.
    names = sorted(spec.name.rsplit("-", 1)[-1] for spec in adapter.cloned)
    assert names == ["dc", "red_attacker"]


# --- stop path --------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_run_tears_down_assets(session: AsyncSession) -> None:
    s = _scenario_with("stopped", [_asset("red_attacker"), _asset("victim")])
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)
    result = await runner.start_run(RunRequest(scenario_id=s.id), session)
    stopped = await runner.stop_run(result.run_id, reason="end of smoke", session=session)

    assert stopped.status == RunStatus.SUCCEEDED  # we left it SUCCEEDED
    for a in stopped.assets:
        assert a.status == AssetStatus.STOPPED
    assert len(adapter.stopped) == 2
    assert len(adapter.destroyed) == 2


@pytest.mark.asyncio
async def test_stop_run_is_idempotent(session: AsyncSession) -> None:
    s = _scenario_with("twice", [_asset("red_attacker")])
    session.add(s)
    await session.commit()
    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)
    await runner.start_run(RunRequest(scenario_id=s.id), session)
    first = await runner.stop_run(1, session=session)
    second = await runner.stop_run(1, session=session)  # second call must not crash

    # Same run, same final state.
    assert first.id == second.id == 1
    assert second.status == RunStatus.SUCCEEDED


# --- failure paths ----------------------------------------------------------


@pytest.mark.asyncio
async def test_start_run_unknown_scenario_raises(session: AsyncSession) -> None:
    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    with pytest.raises(RunnerError, match="not found"):
        await runner.start_run(RunRequest(scenario_id=999), session)


@pytest.mark.asyncio
async def test_start_run_no_assets_raises(session: AsyncSession) -> None:
    s = _scenario_with("empty", [])
    session.add(s)
    await session.commit()
    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    with pytest.raises(RunnerError, match="no assets"):
        await runner.start_run(RunRequest(scenario_id=s.id), session)


@pytest.mark.asyncio
async def test_start_run_missing_template_fails_run(session: AsyncSession) -> None:
    s = _scenario_with("missing-tpl", [_asset("red_attacker", template="tpl-doesnt-exist")])
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    # NOTE: deliberately do NOT seed tpl-doesnt-exist
    runner = Runner(adapter=adapter)

    with pytest.raises(RunnerError, match="template .* not found"):
        await runner.start_run(RunRequest(scenario_id=s.id), session)

    run = (await session.execute(select(models.Run))).scalar_one()
    assert run.status == RunStatus.FAILED
    assert "template" in (run.error or "").lower()

    asset = (await session.execute(select(models.Asset))).scalar_one()
    assert asset.status == AssetStatus.FAILED


@pytest.mark.asyncio
async def test_start_run_partial_failure_tears_down_clones(session: AsyncSession) -> None:
    """Asset 1 succeeds; asset 2 fails (no template). The runner should
    destroy the successfully-cloned asset 1."""
    s = _scenario_with(
        "partial",
        [
            _asset("a", template="tpl-a"),
            _asset("b", template="tpl-b"),
        ],
    )
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-a", 9000)
    # tpl-b intentionally not seeded -> asset b will fail
    runner = Runner(adapter=adapter)

    with pytest.raises(RunnerError):
        await runner.start_run(RunRequest(scenario_id=s.id), session)

    # At least one non-template VMID should have been destroyed: the
    # successfully-cloned asset 'a'. We can't pin the exact VMID because
    # template seeding already consumed 9000; just count destructions
    # of non-template VMs.
    non_template_destroys = [
        (vmid, node)
        for (vmid, node) in adapter.destroyed
        if vmid != 9000  # the template seed VMID
    ]
    assert non_template_destroys, (
        f"expected asset 'a' VM destroyed, got adapter.destroyed={adapter.destroyed}"
    )


@pytest.mark.asyncio
async def test_start_run_clone_failure_continues_audit(session: AsyncSession) -> None:
    """When the adapter raises mid-clone, we still record the FAILED audit."""
    s = _scenario_with("audit-on-fail", [_asset("only", template="tpl-x")])
    session.add(s)
    await session.commit()

    class ExplodingAdapter(MockProxmoxAdapter):
        async def clone_vm(self, spec: CloneSpec):  # type: ignore[override]
            raise RuntimeError("disk full")

    adapter = ExplodingAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)

    with pytest.raises(RuntimeError, match="disk full"):
        await runner.start_run(RunRequest(scenario_id=s.id), session)

    actions = [
        log.action
        for log in (await session.execute(select(models.AuditLog))).scalars().all()
    ]
    assert AuditAction.RUN_FAILED in actions


# --- adapter contract -------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_adapter_inventory_round_trip() -> None:
    adapter = MockProxmoxAdapter(nodes=["pve-a", "pve-b"])
    assert await adapter.list_nodes() == ["pve-a", "pve-b"]
    adapter.seed_template("tpl-x", 9000)
    assert await adapter.find_template("tpl-x") == 9000
    assert await adapter.find_template("nope") is None
    vmid1 = await adapter.allocate_vmid()
    vmid2 = await adapter.allocate_vmid()
    assert vmid2 == vmid1 + 1


@pytest.mark.asyncio
async def test_mock_adapter_clone_then_state() -> None:
    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    res = await adapter.clone_vm(
        CloneSpec(source_vmid=9000, new_vmid=9100, node="pve", name="alice")
    )
    assert res.vmid == 9100
    state = await adapter.get_vm_state(9100, "pve")
    assert state.status == "stopped"
    await adapter.start_vm(9100, "pve")
    state = await adapter.get_vm_state(9100, "pve")
    assert state.status == "running"


@pytest.mark.asyncio
async def test_mock_adapter_destroy_is_idempotent() -> None:
    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    await adapter.destroy_vm(9999, "pve")  # not present, must not raise
    assert adapter.destroyed == [(9999, "pve")]


@pytest.mark.asyncio
async def test_get_vm_state_missing_raises() -> None:
    adapter = MockProxmoxAdapter()
    with pytest.raises(KeyError):
        await adapter.get_vm_state(12345, "pve")
