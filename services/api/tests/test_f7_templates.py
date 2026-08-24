"""F7: range templates (model + CRUD endpoints).

Three surfaces:

  * Template model -- 4 tests
  * snapshot builder -- 3 tests
  * HTTP endpoints (create/list/detail/delete) -- 7 tests

Total: 14 tests.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import sign_token
from app.db import models
from app.db.session import get_sessionmaker


# --- model -------------------------------------------------------------


def test_models_template_columns():
    cols = {c.name for c in models.Template.__table__.columns}
    expected = {
        "id", "name", "title", "description",
        "from_run_id", "scenario_id", "snapshot",
        "created_by", "created_at", "updated_at",
    }
    assert expected <= cols, f"missing: {expected - cols}"


def test_models_template_name_unique():
    """Template.name is globally unique.

    The unique constraint is declared inline as
    ``sa.UniqueConstraint("name", name="uq_templates_name")``,
    so it lives on ``Template.__table__.constraints`` rather than
    ``__table_args__`` (which only carries Index entries).
    """
    constraints = list(models.Template.__table__.constraints)
    found = False
    for c in constraints:
        if (
            getattr(c, "name", None) == "uq_templates_name"
        ):
            found = True
            assert {col.name for col in c.columns} == {"name"}
    assert found, "uq_templates_name must exist on Template.__table__.constraints"


def test_models_run_has_template_id_column():
    cols = {c.name for c in models.Run.__table__.columns}
    assert "template_id" in cols


def test_models_template_snapshot_is_jsonb():
    """snapshot column is JSON -- we need to dump / load it
    losslessly when the run is reset."""
    cols = list(models.Template.__table__.columns)
    snap = next(c for c in cols if c.name == "snapshot")
    # In SQLAlchemy, JSON covers JSONB on Postgres / TEXT on sqlite.
    assert "JSON" in str(snap.type).upper()


# --- snapshot builder --------------------------------------------------


def _make_run(**kwargs):
    """Build a Run with sensible defaults."""
    defaults = {
        "scenario_id": 1, "status": models.RunStatus.SUCCEEDED,
        "started_by": "alice",
    }
    defaults.update(kwargs)
    return models.Run(**defaults)


def test_snapshot_includes_scenario_id_and_name():
    """The snapshot must be self-contained (scenario_id, name)."""
    from app.routers.templates import _build_snapshot
    from app.db.models import Template  # noqa: F401  -- ensure registered
    sm = get_sessionmaker()

    async def _seed():
        async with sm() as session:
            scen = models.Scenario(
                name=f"snap-{uuid.uuid4().hex[:6]}",
                title="Snapshot Test",
                version=1,
                difficulty="beginner",
                duration_min=30,
                spec={"apiVersion": "divide/v1", "kind": "Scenario",
                       "spec": {"assets": []}},
            )
            session.add(scen)
            await session.commit()
            return scen

    scen = asyncio.run(_seed())
    run = _make_run(scenario_id=scen.id)
    snap = _build_snapshot(run, scen)
    assert snap["scenario_id"] == scen.id
    assert snap["scenario_name"] == scen.name
    assert snap["run_status_at_snapshot"] == "succeeded"


def test_snapshot_carries_assets_and_flags():
    """The snapshot must round-trip the scenario's assets/flags."""
    from app.routers.templates import _build_snapshot
    sm = get_sessionmaker()

    async def _seed():
        async with sm() as session:
            scen = models.Scenario(
                name=f"snap2-{uuid.uuid4().hex[:6]}",
                title="Snapshot Test 2",
                version=1,
                difficulty="beginner",
                duration_min=30,
                spec={
                    "apiVersion": "divide/v1",
                    "kind": "Scenario",
                    "spec": {
                        "assets": [
                            {"role": "victim", "kind": "vm",
                             "template": "tpl-x", "networks": []}
                        ],
                        "flags": [
                            {"id": "f1", "side": "red",
                             "value": "FLAG{x}", "base_points": 100},
                        ],
                    },
                },
            )
            session.add(scen)
            await session.commit()
            return scen

    scen = asyncio.run(_seed())
    run = _make_run(scenario_id=scen.id)
    snap = _build_snapshot(run, scen)
    assert len(snap["assets"]) == 1
    assert snap["assets"][0]["template"] == "tpl-x"
    assert len(snap["flags"]) == 1
    assert snap["flags"][0]["id"] == "f1"


def test_snapshot_records_run_status():
    """Captures the run's status so reset can detect drift."""
    from app.routers.templates import _build_snapshot
    sm = get_sessionmaker()

    async def _seed():
        async with sm() as session:
            scen = models.Scenario(
                name=f"snap3-{uuid.uuid4().hex[:6]}",
                title="Snapshot Test 3",
                version=1, difficulty="beginner", duration_min=30,
                spec={"apiVersion": "divide/v1", "kind": "Scenario",
                       "spec": {"assets": []}},
            )
            session.add(scen)
            await session.commit()
            return scen

    scen = asyncio.run(_seed())
    run = _make_run(scenario_id=scen.id, status=models.RunStatus.FAILED)
    snap = _build_snapshot(run, scen)
    assert snap["run_status_at_snapshot"] == "failed"


# --- HTTP endpoints ----------------------------------------------------


def _seed_scenario_and_succeeded_run() -> tuple[int, int]:
    sm = get_sessionmaker()

    async def _seed():
        async with sm() as session:
            scen = models.Scenario(
                name=f"f7-{uuid.uuid4().hex[:8]}",
                title="F7 Test",
                version=1, difficulty="beginner", duration_min=30,
                spec={
                    "apiVersion": "divide/v1",
                    "kind": "Scenario",
                    "spec": {
                        "assets": [
                            {"role": "victim", "kind": "vm",
                             "template": "tpl-x", "networks": []}
                        ],
                        "flags": [],
                    },
                },
            )
            session.add(scen)
            await session.flush()
            run = models.Run(
                scenario_id=scen.id,
                status=models.RunStatus.SUCCEEDED,
                started_by="alice",
            )
            session.add(run)
            await session.commit()
            return scen.id, run.id

    return tuple(asyncio.run(_seed()))


def test_admin_creates_template_from_succeeded_run():
    scenario_id, run_id = _seed_scenario_and_succeeded_run()
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.post("/api/v1/templates", json={
        "name": f"router-baseline-{uuid.uuid4().hex[:8]}",
        "title": "Router Baseline",
        "description": "Working state",
        "from_run_id": run_id,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scenario_id"] == scenario_id
    assert body["from_run_id"] == run_id
    assert body["snapshot"]["scenario_id"] == scenario_id
    assert body["snapshot"]["run_status_at_snapshot"] == "succeeded"
    assert "assets" in body["snapshot"]


def test_create_template_requires_admin():
    scenario_id, run_id = _seed_scenario_and_succeeded_run()
    from app.main import app
    token = sign_token(sub="alice", role="red", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/templates", json={
        "name": "x", "title": "x",
        "from_run_id": run_id,
    })
    assert r.status_code in (401, 403)


def test_create_template_rejects_running_run():
    """Only terminal runs can be templated (FAILED/SUCCEEDED/ENDED)."""
    sm = get_sessionmaker()

    async def _seed_running():
        async with sm() as session:
            scen = models.Scenario(
                name=f"f7-running-{uuid.uuid4().hex[:8]}",
                title="Running", version=1,
                difficulty="beginner", duration_min=30,
                spec={"apiVersion": "divide/v1", "kind": "Scenario",
                       "spec": {"assets": []}},
            )
            session.add(scen)
            await session.flush()
            run = models.Run(
                scenario_id=scen.id,
                status=models.RunStatus.RUNNING,
                started_by="alice",
            )
            session.add(run)
            await session.commit()
            return run.id

    run_id = asyncio.run(_seed_running())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/templates", json={
        "name": "running-tpl",
        "title": "x",
        "from_run_id": run_id,
    })
    assert r.status_code == 409


def test_create_template_rejects_unknown_run():
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/templates", json={
        "name": "no-run", "title": "x", "from_run_id": 99999,
    })
    assert r.status_code == 404


def test_list_templates_any_role():
    scenario_id, run_id = _seed_scenario_and_succeeded_run()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    red = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="alice", role="red", ttl_s=300
        )}
    )
    admin.post("/api/v1/templates", json={
        "name": f"list-tpl-{uuid.uuid4().hex[:8]}",
        "title": "Listable", "from_run_id": run_id,
    })
    res_admin = admin.get("/api/v1/templates").json()
    res_red = red.get("/api/v1/templates").json()
    assert res_admin["total"] >= 1
    assert res_red["total"] == res_admin["total"]


def test_get_template_404_for_unknown():
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.get("/api/v1/templates/99999")
    assert r.status_code == 404


def test_delete_template_admin_only():
    scenario_id, run_id = _seed_scenario_and_succeeded_run()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    red = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="alice", role="red", ttl_s=300
        )}
    )
    create = admin.post("/api/v1/templates", json={
        "name": f"delete-tpl-{uuid.uuid4().hex[:8]}",
        "title": "Deletable", "from_run_id": run_id,
    }).json()
    r_red = red.delete(f"/api/v1/templates/{create['id']}")
    assert r_red.status_code in (401, 403)
    r_admin = admin.delete(f"/api/v1/templates/{create['id']}")
    assert r_admin.status_code == 200
    assert r_admin.json()["deleted"] == create["id"]
    # And it's gone
    r_after = admin.get(f"/api/v1/templates/{create['id']}")
    assert r_after.status_code == 404


def test_create_template_rejects_duplicate_name():
    scenario_id, run_id = _seed_scenario_and_succeeded_run()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    name = f"dup-{uuid.uuid4().hex[:8]}"
    r1 = admin.post("/api/v1/templates", json={
        "name": name, "title": "first", "from_run_id": run_id,
    })
    assert r1.status_code == 200
    # Second seed a fresh run (so we don't violate the "template
    # from a run" check) and try the same name.
    scenario_id2, run_id2 = _seed_scenario_and_succeeded_run()
    r2 = admin.post("/api/v1/templates", json={
        "name": name, "title": "second", "from_run_id": run_id2,
    })
    assert r2.status_code == 409
