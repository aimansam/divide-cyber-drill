"""Tests for the after-action JSON report endpoint (L2 2.12).

The report endpoint is a read-only composite view of a run:
  * the Run row,
  * a thin Scenario summary,
  * the asset list,
  * the audit-log timeline,
  * a Prometheus-derived metrics_summary.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient


def _now_name(prefix: str) -> str:
    """Unique scenario name per test invocation."""
    return f"{prefix}-{int(time.time() * 1000) % 100000000}"


async def _seed_terminal_run(
    *,
    started_by: str = "alice",
    scenario_name: str | None = None,
    status_value: str = "succeeded",
) -> tuple[int, int]:
    """Seed a scenario + run with assets + audit rows. Returns (run_id, scenario_id)."""
    from datetime import datetime, timezone

    from sqlalchemy import func as sql_func

    from app.db import models as db_models
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    name = scenario_name or _now_name("report-test")
    async with sm() as session:
        s = db_models.Scenario(
            name=name,
            title="Report Test",
            version=1,
            difficulty="smoke",
            duration_min=5,
            tags=[],
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "metadata": {
                    "name": name,
                    "title": "Report Test",
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
        run = db_models.Run(
            scenario_id=s.id,
            status=db_models.RunStatus(status_value),
            started_by=started_by,
        )
        session.add(run)
        await session.flush()
        asset = db_models.Asset(
            run_id=run.id,
            role="drill_vm",
            kind="vm",
            template="tpl-x",
            status=db_models.AssetStatus.RUNNING,
            pve_vmid=9999,
            pve_node="pve",
            pve_ip="10.50.0.10",
        )
        session.add(asset)
        await session.flush()
        audit = db_models.AuditLog(
            action=db_models.AuditAction.RUN_COMPLETED,
            actor=started_by,
            run_id=run.id,
            scenario_id=s.id,
            at=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.commit()
        return run.id, s.id


def _token(sub: str, role: str) -> str:
    from app.core.auth import sign_token

    return sign_token(sub, role, 3600)


@pytest.fixture
def client():
    from app.core.config import get_settings
    from app.db import session as session_module
    from app.services import db as db_module

    get_settings.cache_clear()
    db_module._engine = None
    session_module._session_maker = None
    import importlib

    import app.main as _app_main

    importlib.reload(_app_main)
    return TestClient(_app_main.app)


@pytest.fixture(autouse=True)
def _clean_scenarios():
    """Truncate scenarios + cascading runs/assets/audit before each test.

    Other test files in this suite (e.g. test_routers.py) assume an
    EMPTY database. Our seed_terminal_run leaves rows behind; an
    autouse teardown is the cheapest way to keep both passing.
    """
    from sqlalchemy import delete

    from app.db import models as db_models
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    yield  # test runs first

    async def _cleanup():
        async with sm() as s:
            await s.execute(delete(db_models.AuditLog))
            await s.execute(delete(db_models.Asset))
            await s.execute(delete(db_models.Run))
            await s.execute(delete(db_models.Scenario))
            await s.commit()

    try:
        asyncio.run(_cleanup())
    except Exception:  # noqa: BLE001 — best-effort
        pass


def test_report_200_shape_for_terminal_run(client):
    """A terminal (succeeded) run returns the full report shape."""
    run_id, _ = asyncio.run(_seed_terminal_run())
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "admin")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"run", "scenario", "assets", "audit", "metrics_summary"}
    assert body["run"]["id"] == run_id
    assert body["run"]["status"] == "succeeded"
    assert len(body["assets"]) == 1
    assert body["assets"][0]["role"] == "drill_vm"
    assert len(body["audit"]) >= 1
    assert body["scenario"]["name"].startswith("report-test-")


def test_report_404_unknown_run(client):
    r = client.get(
        "/api/v1/drills/9999999/report",
        headers={"X-Divide-Token": _token("alice", "admin")},
    )
    assert r.status_code == 404


def test_report_403_red_cannot_see_anothers_run(client):
    """A red user requesting another red user's run gets 403."""
    run_id, _ = asyncio.run(_seed_terminal_run(started_by="bob"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "red")},
    )
    assert r.status_code == 403
    assert "do not have access" in r.json()["detail"]


def test_report_200_red_can_see_own_run(client):
    """A red user requesting their own run gets 200."""
    run_id, _ = asyncio.run(_seed_terminal_run(started_by="alice"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "red")},
    )
    assert r.status_code == 200, r.text


def test_report_200_admin_can_see_any_run(client):
    """Admin sees any run regardless of started_by."""
    run_id, _ = asyncio.run(_seed_terminal_run(started_by="bob"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("ops", "admin")},
    )
    assert r.status_code == 200


def test_report_200_lead_can_see_any_run(client):
    """Lead sees any run."""
    run_id, _ = asyncio.run(_seed_terminal_run(started_by="bob"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("ops", "lead")},
    )
    assert r.status_code == 200


def test_report_200_observer_can_see_any_run(client):
    """Observer sees any run (read-only persona)."""
    run_id, _ = asyncio.run(_seed_terminal_run(started_by="bob"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("auditor", "observer")},
    )
    assert r.status_code == 200


def test_report_409_for_in_progress_run(client):
    """A run still in PENDING or RUNNING returns 409."""
    run_id, _ = asyncio.run(_seed_terminal_run(status_value="running"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "admin")},
    )
    assert r.status_code == 409
    assert "non-terminal" in r.json()["detail"]


def test_report_409_for_pending_run(client):
    """PENDING also returns 409."""
    run_id, _ = asyncio.run(_seed_terminal_run(status_value="pending"))
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "admin")},
    )
    assert r.status_code == 409


def test_report_401_anonymous(client):
    r = client.get("/api/v1/drills/1/report")
    assert r.status_code == 401


def test_report_metrics_summary_has_runs_total_block(client):
    """metrics_summary carries the runs_total_{outcome} counters."""
    run_id, _ = asyncio.run(_seed_terminal_run())
    r = client.get(
        f"/api/v1/drills/{run_id}/report",
        headers={"X-Divide-Token": _token("alice", "admin")},
    )
    body = r.json()
    ms = body["metrics_summary"]
    assert "captured_at" in ms
    assert "by_scenario_id" in ms
    assert any(k.startswith("runs_total_") for k in ms)