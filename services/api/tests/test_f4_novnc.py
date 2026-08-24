"""F4: noVNC console per asset.

The runner already knows the ``pve_vmid`` and ``pve_node`` of
each asset; what it didn't provide was a way for the portal /
operator to actually look at the VM screen. F4 closes that
gap:

  * ProxmoxAdapter: ``get_vnc_ticket(vmid, node) -> VncTicket``
  * RealProxmoxAdapter: POST /nodes/{n}/qemu/{v}/vncproxy,
    return the PVE-issued ticket + port
  * MockProxmoxAdapter: deterministic ``mock-ticket-NNNN`` so
    tests can assert exact values
  * HTTP GET /drills/{id}/assets/{a}/console: returns the
    ticket, port, ws_path, etc. RBAC + cloned-status checks.
  * WS proxy /drills/{id}/assets/{a}/console/ws: accepts the
    upgrade with X-Divide-Token, validates RBAC + ticket,
    pumps bytes between browser and PVE upstream.

This suite pins the HTTP surface (mocking the WS) end-to-end.
The WS proxy unit tests live in
``test_console_proxy.py`` (next file) and assert the
bidirectional pump.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import sign_token
from app.db import models
from app.db.session import get_sessionmaker
from app.runners.adapter import VncTicket
from app.runners.mock_adapter import MockProxmoxAdapter


# --- fixtures ------------------------------------------------------------


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


@pytest.fixture
async def adapter():
    a = MockProxmoxAdapter(templates={"tpl-x": 9000})
    # Spawn one running VM so get_vnc_ticket works (mock refuses
    # tickets for stopped VMs).
    from app.runners.adapter import CloneSpec
    await a.clone_vm(
        CloneSpec(
            source_vmid=9000,
            new_vmid=9100,
            node="pve",
            name="victim",
        )
    )
    await a.start_vm(9100, "pve")
    return a



# --- adapter surface -----------------------------------------------------




def _mock_with_vmid(vmid: int, node: str):
    """Return a Runner built on a mock with vmid already cloned + started.

    The TestClient HTTP tests run in the same event loop as the
    runner, so we can't asyncio.run() here — the adapter's
    internal _vms dict can be populated synchronously instead.
    """
    from app.runners.runner import Runner
    adapter = MockProxmoxAdapter(templates={"tpl-x": 9000})
    # Pre-register the VM directly into the mock's internal map.
    from app.runners.mock_adapter import _Vm
    adapter._vms[vmid] = _Vm(
        vmid=vmid, node=node, name="v", status="running", ip="10.0.0.1"
    )
    adapter._bridges = set()  # no F3 bridges for these tests
    return Runner(adapter=adapter)

async def _seed_run_with_asset(
    *, started_by: str = "alice", planned: bool = False
) -> tuple[int, int]:
    """Seed a scenario + run + asset directly in the API's DB."""
    import asyncio
    from app.db.session import get_sessionmaker  # noqa
    sm = get_sessionmaker()
    async with sm() as session:
        import uuid
        scen = models.Scenario(
            name=f"novnc-{uuid.uuid4().hex[:8]}",
            title="novnc-test",
            version=1,
            difficulty="beginner",
            duration_min=30,
            spec={"apiVersion": "divide/v1", "kind": "Scenario",
                   "spec": {"assets": []}},
        )
        session.add(scen)
        await session.flush()
        run = models.Run(
            scenario_id=scen.id,
            status=models.RunStatus.RUNNING,
            started_by=started_by,
        )
        session.add(run)
        await session.flush()
        asset = models.Asset(
            run_id=run.id,
            role="victim",
            kind="vm",
            template="tpl-x",
            status=(
                models.AssetStatus.PLANNED if planned
                else models.AssetStatus.RUNNING
            ),
            pve_vmid=None if planned else 9100,
            pve_node=None if planned else "pve",
        )
        session.add(asset)
        await session.commit()
    return run.id, asset.id


@pytest.mark.asyncio
async def test_mock_adapter_issues_deterministic_ticket(adapter):
    """The mock returns a deterministic ticket so tests can assert."""
    t = await adapter.get_vnc_ticket(9100, "pve")
    assert isinstance(t, VncTicket)
    assert t.ticket == "mock-ticket-238c"  # 9100 hex
    assert t.port == 5900 + 9100 % 1000  # 6900
    assert t.vmid == 9100
    assert t.node == "pve"


@pytest.mark.asyncio
async def test_mock_adapter_records_vnc_ticket_calls(adapter):
    """The call history is recorded for observability + assertions."""
    await adapter.get_vnc_ticket(9100, "pve")
    await adapter.get_vnc_ticket(9100, "pve")
    assert adapter.vnc_tickets == [(9100, "pve"), (9100, "pve")]


@pytest.mark.asyncio
async def test_mock_adapter_refuses_vnc_for_stopped_vm():
    """PVE refuses to issue VNC tickets for stopped VMs; mock matches."""
    a = MockProxmoxAdapter(templates={"tpl-x": 9000})
    from app.runners.mock_adapter import _Vm
    a._vms[9100] = _Vm(vmid=9100, node="pve", name="v", status="stopped")
    with pytest.raises(RuntimeError, match="not running"):
        await a.get_vnc_ticket(9100, "pve")


@pytest.mark.asyncio
async def test_mock_adapter_refuses_vnc_for_unknown_vmid():
    """Asking for a ticket on a vmid that doesn't exist raises KeyError."""
    a = MockProxmoxAdapter()
    with pytest.raises(KeyError):
        await a.get_vnc_ticket(99999, "pve")


# --- HTTP endpoint -------------------------------------------------------


def test_get_asset_console_returns_ticket_url():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice"))

    """End-to-end through the router: a running asset returns a
    valid ticket + ws_path. Uses TestClient to drive the HTTP layer."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.runners import runner as runner_mod

    # Pin the runner to the in-process mock so we don't try PVE.
    runner_mod.build_runner = lambda: _mock_with_vmid(9100, "pve")

    token = sign_token(sub="alice", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.get(
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_id"] == asset_id
    assert body["run_id"] == run_id
    assert body["vmid"] == 9100
    assert body["node"] == "pve"
    assert body["ticket"].startswith("mock-ticket-")
    assert body["ws_path"] == (
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console/ws"
    )
    assert body["expires_in_seconds"] == 7200


def test_get_asset_console_404_when_asset_not_found():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice"))

    """Asset id that doesn't exist -> 404, no leakage of existence."""
    from fastapi.testclient import TestClient
    from app.main import app

    token = sign_token(sub="alice", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.get(f"/api/v1/drills/{run_id}/assets/99999/console")
    assert r.status_code == 404
    assert "not found" in r.text


def test_get_asset_console_409_when_asset_not_yet_cloned():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice", planned=True))

    """An asset that hasn't been cloned returns 409, not 500."""
    from fastapi.testclient import TestClient
    from app.main import app

    token = sign_token(sub="alice", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.get(
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console"
    )
    assert r.status_code == 409
    assert "not been cloned" in r.text


def test_get_asset_console_403_for_other_run_started_by():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice"))

    """A red/blue who didn't start the run can't open console."""
    from fastapi.testclient import TestClient
    from app.main import app

    token = sign_token(sub="eve", role="red", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.get(
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console"
    )
    assert r.status_code == 403


def test_get_asset_console_admin_sees_any_run():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice"))

    """Admin can see anyone's run."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.runners import runner as runner_mod

    runner_mod.build_runner = lambda: _mock_with_vmid(9100, "pve")

    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.get(
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console",
    )
    assert r.status_code == 200


def test_get_asset_console_requires_token():
    run_id, asset_id = asyncio.run(_seed_run_with_asset(started_by="alice"))

    """No token -> 401."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.get(
        f"/api/v1/drills/{run_id}/assets/{asset_id}/console"
    )
    assert r.status_code in (401, 403)
