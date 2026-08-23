"""End-to-end smoke tests for the cancel paths.

What this covers (all against MockProxmoxAdapter -- zero PVE needed):

  1. ``make live-cancel`` shape:
     stand up a RUNNING run + its asset, call Runner.cancel_run, verify:
       - Run.status == CANCELLED
       - Run.error == reason (recorded in DB so audit/UI can show it)
       - Run.ended_at is set
       - cancel counter for "already_terminal" did NOT tick
       - the audit log has RUN_CANCELLED with the reason in details

  2. ``make watch-drill --cancel-after N``:
     drive tools/watch_drill.py with --cancel-after against a mocked API.
     Asserts the watcher POSTs /drills/{id}/cancel and exits 0.

  3. ``make live-cancel`` on a finished run produces a clear 409
     (so ``watch_drill`` exits non-zero with a meaningful hint).

  4. Cancel a run that doesn't exist returns 404.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.db import models
from app.db.base import Base
from app.db.models import AssetStatus, AuditAction, RunStatus
from app.observability import CANCEL_REQUESTS_TOTAL
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunnerError, RunRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------- fixtures --------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


def _scenario(name: str = "cancel-smoke", assets=("vm_a",)) -> models.Scenario:
    asset_specs = [
        {
            "role": role,
            "kind": "vm",
            "template": "tpl-x",
            "networks": ["n"],
        }
        for role in assets
    ]
    return models.Scenario(
        name=name,
        title=name,
        version=1,
        difficulty="beginner",
        duration_min=30,
        spec={
            "apiVersion": "divide/v1",
            "kind": "Scenario",
            "spec": {"assets": asset_specs},
        },
    )


async def _make_running_run(
    session: AsyncSession,
    scenario_name: str = "cancel-smoke-live",
    asset_count: int = 1,
) -> tuple[int, int]:
    """Stand up a Run + Assets that look like a RUNNING drill, manually.

    Returns ``(run_id, scenario_id)``.

    Why manual, not via Runner.start_run? Because the Mock adapter's
    spawn loop completes in a few ms; the production Runner only ever
    sees RUNNING briefly. To test the cancel path against a stable
    "still RUNNING" row, we insert the rows directly. This is what
    production cancel looks like: cancel_run() hits a row that the
    runner had time to flip from PENDING to RUNNING but hasn't yet
    transitioned to a terminal state.

    Note: ``Runner.cancel_run`` takes a session and runs in that
    transaction. We commit before calling it so the row is visible
    from the cancel transaction.
    """
    sc = _scenario(scenario_name, assets=tuple(f"vm_{i}" for i in range(asset_count)))
    session.add(sc)
    await session.flush()

    run = models.Run(
        scenario_id=sc.id,
        status=RunStatus.RUNNING,
        started_at=datetime.now(UTC),
        started_by="cancel-smoke",
    )
    session.add(run)
    await session.flush()

    for i in range(asset_count):
        session.add(
            models.Asset(
                run_id=run.id,
                role=f"vm_{i}",
                kind="vm",
                template="tpl-x",
                status=AssetStatus.RUNNING,
                pve_vmid=9000 + i,
                pve_node="pve",
            )
        )
    await session.commit()
    return run.id, sc.id


# ---------- live-cancel shape ----------------------------------------------


@pytest.mark.asyncio
async def test_live_cancel_marks_run_cancelled_with_reason(session: AsyncSession) -> None:
    """``make live-cancel`` mid-flight: 4 post-conditions operators care about.

    The actual end-to-end ``make live-cancel`` flow is:
      1. POST /api/v1/drills    (run spawned, becomes RUNNING)
      2. wait N seconds
      3. POST /api/v1/drills/{id}/cancel   <-- this is what we test below
      4. wait for /api/v1/drills/{id}.status == "cancelled"

    Step 3-4 is what Runner.cancel_run does. This test asserts that
    cancel_run: marks Run.status=CANCELLED, sets Run.error to the
    reason, sets Run.ended_at, and writes a RUN_CANCELLED audit entry.
    """
    run_id, _scenario_id = await _make_running_run(session)

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", vmid=9000)
    runner = Runner(adapter=adapter)
    cancelled = await runner.cancel_run(
        run_id,
        reason="operator-pressed-cancel",
        session=session,
    )

    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.error == "operator-pressed-cancel"
    assert cancelled.ended_at is not None

    audit_rows = (
        await session.execute(
            select(models.AuditLog)
            .where(models.AuditLog.run_id == run_id)
            .where(models.AuditLog.action == AuditAction.RUN_CANCELLED)
        )
    ).scalars().all()
    assert len(audit_rows) == 1, f"expected 1 RUN_CANCELLED audit row, got {len(audit_rows)}"
    assert audit_rows[0].details.get("reason") == "operator-pressed-cancel"


@pytest.mark.asyncio
async def test_live_cancel_does_not_tick_already_terminal_counter(
    session: AsyncSession,
) -> None:
    """A successful cancel must NOT increment the 'already_terminal' counter.

    That's the regression we want to catch: cancel_run() running on a
    RUNNING run is *the happy path*. The router records the cancel
    via record_cancel(result="ok") for happy-path cancels, never
    "already_terminal".
    """
    run_id, _ = await _make_running_run(session)
    before = CANCEL_REQUESTS_TOTAL.labels(result="already_terminal")._value.get()

    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", vmid=9000)
    runner = Runner(adapter=adapter)
    await runner.cancel_run(run_id, session=session)

    after = CANCEL_REQUESTS_TOTAL.labels(result="already_terminal")._value.get()
    assert after == before, (
        f"already_terminal counter must not tick on a happy-path cancel: "
        f"{before} -> {after}"
    )


# ---------- watch_drill --cancel-after path -------------------------------


def test_watch_drill_cancel_after_path_triggers_cancel_endpoint(monkeypatch) -> None:
    """Drive tools/watch_drill.py with --cancel-after against a mocked API.

    Asserts:
      * The watcher detects an in-flight drill via /api/v1/drills
      * After --cancel-after elapses, it POSTs /drills/{id}/cancel
      * It exits 0 (rc == 0) when the run reaches cancelled
    """
    import httpx

    cancel_calls: list[str] = []
    state = {"poll_count": 0}

    def list_drills(req: httpx.Request) -> httpx.Response:
        state["poll_count"] += 1
        # First poll: a single running run. Second poll: cancelled.
        if state["poll_count"] == 1:
            runs = [{"run_id": 99, "scenario_id": 3, "status": "running"}]
        else:
            runs = [{"run_id": 99, "scenario_id": 3, "status": "cancelled"}]
        return httpx.Response(200, json={"items": runs})

    def cancel(req: httpx.Request) -> httpx.Response:
        cancel_calls.append(str(req.url))
        return httpx.Response(
            200,
            json={
                "run_id": 99,
                "status": "cancelled",
                "reason": "watch-drill-cancel-after",
                "assets": [],
            },
        )

    def prom_query(_: httpx.Request) -> httpx.Response:
        # Always report zero counters so the watcher doesn't try to
        # exit on Prometheus alone; force it to use api-poll fallback.
        return httpx.Response(
            200, json={"status": "success", "data": {"result": []}}
        )

    handlers = {
        "http://localhost:8000/api/v1/drills/99/cancel": cancel,
        "http://localhost:8000/api/v1/drills": list_drills,
        "http://localhost:9090/api/v1/query": prom_query,
    }

    def _route(request: httpx.Request) -> httpx.Response:
        for prefix, handler in handlers.items():
            if str(request.url).startswith(prefix):
                return handler(request)
        return httpx.Response(404, json={"detail": "no handler"})

    transport = httpx.MockTransport(_route)
    original_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)

    # Load watch_drill.py as a module (so monkeypatching httpx.Client takes).
    spec = importlib.util.spec_from_file_location(
        "watch_drill",
        Path(__file__).resolve().parents[3] / "tools" / "watch_drill.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["watch_drill"] = mod
    spec.loader.exec_module(mod)

    # Cancel after 0s, timeout 10s, poll every 50ms. --api-poll forces
    # the API path because Prometheus never increments in this test.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watch_drill.py",
            "--cancel-after", "0",
            "--outcome", "cancelled",
            "--timeout", "10",
            "--poll", "0.05",
            "--api-poll",
        ],
    )
    rc = mod.main()
    assert rc == 0, f"watch_drill main() returned {rc}"
    assert cancel_calls, "watch_drill never POSTed /drills/99/cancel"


# ---------- 404 / 409 paths (drive watch_drill's error messages) ----------


@pytest.mark.asyncio
async def test_cancel_unknown_run_raises_runner_error(session: AsyncSession) -> None:
    """``watch_drill`` on a missing run_id yields a clear 404-shaped error."""
    runner = Runner(adapter=MockProxmoxAdapter())
    with pytest.raises(RunnerError) as ei:
        await runner.cancel_run(9999, session=session)
    assert "not found" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_cancel_already_succeeded_run_raises_409(session: AsyncSession) -> None:
    """``watch_drill`` on a finished run must produce a clear 'already terminal' error.

    The router maps this to HTTP 409, so ``watch_drill`` exits
    non-zero with a meaningful hint instead of silently doing nothing.
    This is what motivated L1 1.12 (the cancel watcher was never
    executed -- these tests fill the gap).
    """
    adapter = MockProxmoxAdapter()
    adapter.seed_template("tpl-x", vmid=9000)
    sc = _scenario("cancel-after-success", assets=("vm_a",))
    session.add(sc)
    await session.commit()

    runner = Runner(adapter=adapter)
    await runner.start_run(
        RunRequest(scenario_id=sc.id, started_by="cancel-after-success"),
        session=session,
    )
    run = (
        await session.execute(
            select(models.Run).where(models.Run.scenario_id == sc.id)
        )
    ).scalar_one()
    assert run.status == RunStatus.SUCCEEDED

    with pytest.raises(RunnerError) as ei:
        await runner.cancel_run(run.id, session=session)
    msg = str(ei.value).lower()
    assert "already" in msg or "terminal" in msg
