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
async def test_start_run_asset_spawned_audit_records_actor(session: AsyncSession) -> None:
    """Regression for L2 2.9: every ASSET_SPAWNED audit row must carry the
    token subject (i.e. Run.started_by) — not NULL. The router already
    threads ``started_by`` through RunRequest -> Run.started_by; the
    runner's _spawn_asset() used to omit the actor on its _audit call,
    so all per-asset lifecycle events were unattributed.
    """
    s = _scenario_with("attributed", [_asset("red_attacker"), _asset("dc")])
    session.add(s)
    await session.commit()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", 9000)
    runner = Runner(adapter=adapter)

    result = await runner.start_run(
        RunRequest(scenario_id=s.id, started_by="alice"), session
    )
    assert result.status == RunStatus.SUCCEEDED

    spawn_audits = (
        await session.execute(
            select(models.AuditLog).where(
                models.AuditLog.run_id == result.run_id,
                models.AuditLog.action == AuditAction.ASSET_SPAWNED,
            )
        )
    ).scalars().all()
    # Two assets -> two spawn events; both must be attributed.
    assert len(spawn_audits) == 2
    for entry in spawn_audits:
        assert entry.actor == "alice", (
            f"ASSET_SPAWNED audit row missing actor: {entry.actor!r}"
        )
        assert entry.asset_id is not None
        assert entry.run_id == result.run_id


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
    # Asset names embed role; check both roles show up. Note that the
    # runner sanitizes underscores from the role before passing it to
    # PVE (PVE 9 rejects DNS-invalid names on the clone endpoint), so
    # 'red_attacker' becomes 'redattacker'.
    names = sorted(spec.name.rsplit("-", 1)[-1] for spec in adapter.cloned)
    assert names == ["dc", "redattacker"]


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




# --- cancel_run -----------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run_tears_down_and_marks_cancelled(session: AsyncSession) -> None:
    """A run in RUNNING must cancel cleanly: assets stopped + destroyed,
    run flips to CANCELLED, audit row records actor + reason.

    We construct the run/asset state directly (rather than via start_run)
    because start_run completes synchronously with the mock — by the time
    it returns, status is SUCCEEDED. The runner's lifecycle model
    assumes a non-terminal state when cancel arrives; in production the
    portal would call cancel mid-flight via the background task model.
    """
    s = _scenario_with("cancelled", [_asset("red_attacker"), _asset("victim")])
    session.add(s)
    await session.flush()
    run = models.Run(
        scenario_id=s.id,
        status=RunStatus.RUNNING,
        started_by="unit",
    )
    session.add(run)
    await session.flush()
    # Two assets with VMIDs (pretend spawn already happened).
    for role, vmid in [("red_attacker", 9100), ("victim", 9101)]:
        session.add(
            models.Asset(
                run_id=run.id,
                role=role,
                kind="vm",
                template="tpl-x",
                status=AssetStatus.RUNNING,
                pve_vmid=vmid,
                pve_node="pve",
            )
        )
    await session.commit()

    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    cancelled = await runner.cancel_run(
        run.id, reason="trainee pressed abort", actor="trainee-7", session=session
    )

    assert cancelled.id == run.id
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.error == "trainee pressed abort"
    for a in cancelled.assets:
        assert a.status == AssetStatus.STOPPED
    # Adapter saw stop (forced) + destroy for every spawned asset.
    assert len(adapter.stopped) == 2
    assert all(force for (_v, _n, force) in adapter.stopped)
    assert len(adapter.destroyed) == 2

    # Audit row recorded with actor + reason.
    audits = (
        await session.execute(
            select(models.AuditLog).where(models.AuditLog.run_id == run.id)
        )
    ).scalars().all()
    actions = {a.action for a in audits}
    assert AuditAction.RUN_CANCELLED in actions
    cancel_audit = next(a for a in audits if a.action == AuditAction.RUN_CANCELLED)
    assert cancel_audit.actor == "trainee-7"
    assert cancel_audit.details["reason"] == "trainee pressed abort"


@pytest.mark.asyncio
async def test_cancel_run_on_unknown_run_raises(session: AsyncSession) -> None:
    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    with pytest.raises(RunnerError, match="not found"):
        await runner.cancel_run(9999, session=session)


@pytest.mark.asyncio
async def test_cancel_run_on_terminal_run_raises(session: AsyncSession) -> None:
    """A run that has already reached a terminal state cannot be cancelled."""
    s = _scenario_with("already_done", [_asset("red_attacker")])
    session.add(s)
    await session.flush()
    run = models.Run(
        scenario_id=s.id,
        status=RunStatus.SUCCEEDED,
        started_by="unit",
    )
    session.add(run)
    await session.commit()

    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    with pytest.raises(RunnerError, match="terminal state"):
        await runner.cancel_run(run.id, session=session)


@pytest.mark.asyncio
async def test_cancel_run_isolates_from_stop_run_semantics(
    session: AsyncSession,
) -> None:
    """cancel_run -> CANCELLED, stop_run -> SUCCEEDED. Same teardown,
    different terminal state — proves the two paths don't alias."""
    s = _scenario_with("lifecycle_test", [_asset("red_attacker")])
    session.add(s)
    await session.flush()

    # cancel path
    run_cancel = models.Run(
        scenario_id=s.id, status=RunStatus.RUNNING, started_by="unit"
    )
    session.add(run_cancel)
    await session.flush()
    session.add(
        models.Asset(
            run_id=run_cancel.id, role="red_attacker", kind="vm",
            template="tpl-x", status=AssetStatus.RUNNING,
            pve_vmid=9100, pve_node="pve",
        )
    )
    await session.commit()

    adapter1 = MockProxmoxAdapter()
    runner1 = Runner(adapter=adapter1)
    out_cancel = await runner1.cancel_run(run_cancel.id, session=session)
    assert out_cancel.status == RunStatus.CANCELLED

    # stop path (separate run)
    run_stop = models.Run(
        scenario_id=s.id, status=RunStatus.RUNNING, started_by="unit"
    )
    session.add(run_stop)
    await session.flush()
    session.add(
        models.Asset(
            run_id=run_stop.id, role="red_attacker", kind="vm",
            template="tpl-x", status=AssetStatus.RUNNING,
            pve_vmid=9200, pve_node="pve",
        )
    )
    await session.commit()

    adapter2 = MockProxmoxAdapter()
    runner2 = Runner(adapter=adapter2)
    out_stop = await runner2.stop_run(run_stop.id, session=session)
    assert out_stop.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_cancel_run_handles_no_assets_yet(session: AsyncSession) -> None:
    """A run in PENDING (no spawned assets yet) must cancel cleanly
    without any adapter calls."""
    s = _scenario_with("pending", [_asset("red_attacker")])
    session.add(s)
    await session.commit()

    run = models.Run(
        scenario_id=s.id, status=RunStatus.PENDING, started_by="unit"
    )
    session.add(run)
    await session.commit()

    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    cancelled = await runner.cancel_run(
        run.id, reason="aborted before start", session=session
    )
    assert cancelled.status == RunStatus.CANCELLED
    assert adapter.stopped == []
    assert adapter.destroyed == []


@pytest.mark.asyncio
async def test_cancel_run_records_error_as_reason(session: AsyncSession) -> None:
    """Run.error stores the cancel reason so the UI can show 'why'."""
    s = _scenario_with("why_cancelled", [_asset("red_attacker")])
    session.add(s)
    await session.flush()
    run = models.Run(
        scenario_id=s.id, status=RunStatus.RUNNING, started_by="unit"
    )
    session.add(run)
    await session.flush()
    session.add(
        models.Asset(
            run_id=run.id, role="red_attacker", kind="vm",
            template="tpl-x", status=AssetStatus.PLANNED,
            pve_vmid=None, pve_node=None,
        )
    )
    await session.commit()

    adapter = MockProxmoxAdapter()
    runner = Runner(adapter=adapter)
    out = await runner.cancel_run(
        run.id, reason="scoring threshold already met", session=session
    )
    assert out.error == "scoring threshold already met"
