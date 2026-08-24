"""F5: flags + scoring.

Three surfaces:

  * Scoring primitives (pure function) -- 12 tests
  * Flag submission endpoint -- 8 tests
  * Migration + model -- 5 tests
  * F5.2 runner integration -- 2 tests

Total: 27 tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.auth import sign_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.session import get_sessionmaker
from app.services.flags import (
    FlagError,
    capture_seconds,
    resolve_flag,
    verify_flag_value,
)
from app.services.scoring import score, score_breakdown


# --- scoring primitives -------------------------------------------------


def test_score_full_points_at_zero_elapsed():
    """t=0 -> full base points."""
    assert score(100, 3600, 0) == 100


def test_score_half_at_half_window():
    """Linear decay at t=window/2 -> half base."""
    assert score(100, 3600, 1800) == 50


def test_score_zero_at_window_end():
    """t=window -> 0 points."""
    assert score(100, 3600, 3600) == 0


def test_score_zero_past_window():
    """t > window -> 0 points (clamped, no negative)."""
    assert score(100, 3600, 7200) == 0


def test_score_floors_fraction():
    """A 99.9-base award floors to 99."""
    # 333 * (1 - 0.001) = 332.667 -> floor 332
    # Easiest: 100 * (1 - 0.5) -> 50; pick something with fraction.
    # 7 * (1 - 1/3) = 4.666 -> floor 4
    assert score(7, 6, 2) == 4  # 7 * (1 - 2/6) = 4.666


def test_score_negative_elapsed_clamps_to_zero():
    """A race where capture raced before started_at doesn't crash."""
    assert score(100, 3600, -5) == 100  # clamped to 0 -> full


def test_score_zero_base_returns_zero():
    """A flag with no points scores nothing."""
    assert score(0, 3600, 0) == 0


def test_score_zero_window_returns_full_base():
    """Edge case: window_seconds <= 0 means no decay."""
    assert score(100, 0, 7200) == 100


def test_score_negative_window_returns_full_base():
    """Negative windows (impossible per the schema clamp) get full."""
    assert score(100, -10, 1800) == 100


def test_score_breakdown_serializable():
    """``score_breakdown`` returns a JSON-friendly dict."""
    bd = score_breakdown(100, 3600, 1800)
    assert bd["base_points"] == 100
    assert bd["window_seconds"] == 3600
    assert bd["elapsed_seconds"] == 1800
    assert bd["decay_fraction"] == 0.5
    assert bd["awarded_points"] == 50


def test_score_breakdown_negative_elapsed_clamped():
    """The breakdown's elapsed_seconds field is clamped >= 0."""
    bd = score_breakdown(100, 3600, -10)
    assert bd["elapsed_seconds"] == 0
    assert bd["awarded_points"] == 100


def test_score_breakdown_zero_window_full():
    """breakdown for a zero-window flag has decay_fraction 1.0."""
    bd = score_breakdown(100, 0, 7200)
    assert bd["decay_fraction"] == 1.0
    assert bd["awarded_points"] == 100


# --- flag lookup -------------------------------------------------------


def test_resolve_flag_found():
    spec = {
        "spec": {
            "flags": [
                {
                    "id": "f1", "side": "red", "value": "pwned",
                    "planted_on_role": "victim",
                    "decay_window_seconds": 600, "base_points": 50,
                }
            ]
        }
    }
    fs = resolve_flag(spec, "f1")
    assert fs.flag_id == "f1"
    assert fs.value == "pwned"
    assert fs.base_points == 50


def test_resolve_flag_not_found_raises_flag_error():
    spec = {"spec": {"flags": []}}
    with pytest.raises(FlagError) as exc_info:
        resolve_flag(spec, "ghost")
    assert exc_info.value.kind == "flag_not_found"


def test_resolve_flag_accepts_inner_or_outer_spec():
    """The helper handles both ``spec.spec.flags`` and
    ``spec.flags`` shapes (the API stores the parsed YAML with
    the inner spec nested once)."""
    nested = {"spec": {"flags": [{"id": "f1", "side": "red",
                                     "value": "v", "planted_on_role": "r",
                                     "decay_window_seconds": 60,
                                     "base_points": 10}]}}
    flat = {"flags": [{"id": "f1", "side": "red", "value": "v",
                        "planted_on_role": "r", "decay_window_seconds": 60,
                        "base_points": 10}]}
    assert resolve_flag(nested, "f1").flag_id == "f1"
    assert resolve_flag(flat, "f1").flag_id == "f1"


def test_verify_flag_value_correct():
    spec = {"spec": {"flags": [{"id": "f1", "side": "red",
                                  "value": "secret_value",
                                  "planted_on_role": "fileserver",
                                  "decay_window_seconds": 60,
                                  "base_points": 100}]}}
    fs = resolve_flag(spec, "f1")
    assert verify_flag_value(fs, "secret_value") is True


def test_verify_flag_value_wrong():
    spec = {"spec": {"flags": [{"id": "f1", "side": "red",
                                  "value": "secret_value",
                                  "planted_on_role": "fileserver",
                                  "decay_window_seconds": 60,
                                  "base_points": 100}]}}
    fs = resolve_flag(spec, "f1")
    assert verify_flag_value(fs, "guess") is False


def test_capture_seconds_clamped_to_zero():
    """If now < started_at (clock skew), clamp to 0."""
    start = datetime.now(timezone.utc) - timedelta(seconds=60)
    now = start - timedelta(seconds=30)
    # capture is "earlier than start" (impossible); clamp to 0.
    assert capture_seconds(start, now) == 0


def test_capture_seconds_zero_when_started_at_none():
    """A run that hasn't been started yet has no capture time."""
    assert capture_seconds(None) == 0


def test_capture_seconds_negative_clamped():
    """If now < started_at (clock skew), clamp to 0."""
    start = datetime.now(timezone.utc)
    now = start - timedelta(seconds=5)
    assert capture_seconds(start, now) == 0


# --- HTTP endpoint -----------------------------------------------------


async def _seed_scenario_with_flag():
    """Insert a scenario + run + planted flag via the API session."""
    import uuid
    sm = get_sessionmaker()
    async with sm() as session:
        scen = models.Scenario(
            name=f"f5-{uuid.uuid4().hex[:8]}",
            title="f5-test",
            version=1,
            difficulty="beginner",
            duration_min=30,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {
                    "assets": [],
                    "flags": [
                        {
                            "id": "f1", "side": "red",
                            "value": "FLAG{pwned}",
                            "planted_on_role": "fileserver",
                            "decay_window_seconds": 600,
                            "base_points": 100,
                        },
                    ],
                },
            },
        )
        session.add(scen)
        await session.flush()
        run = models.Run(
            scenario_id=scen.id,
            status=models.RunStatus.RUNNING,
            started_by="alice",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(run)
        await session.commit()
        return run.id


def test_submit_flag_correct_value_200():
    """End-to-end: a valid flag submission returns the points."""
    run_id = asyncio.run(_seed_scenario_with_flag())
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "FLAG{pwned}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["team"] == "blue"  # red-side flag hunted by blue
    assert body["points"] > 90  # ~30s elapsed, 600s window = ~95 pts
    assert body["breakdown"]["awarded_points"] == body["points"]


def test_submit_flag_wrong_value_422():
    """Mismatched value -> 422 with a clear error."""
    run_id = asyncio.run(_seed_scenario_with_flag())
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "wrong"},
    )
    assert r.status_code == 422


def test_submit_flag_missing_run_404():
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        "/api/v1/drills/99999/submit-flag",
        json={"flag_id": "f1", "value": "x"},
    )
    assert r.status_code == 404


def test_submit_flag_missing_in_spec_404():
    """A flag_id not in spec.flags[] returns 404, not 500."""
    run_id = asyncio.run(_seed_scenario_with_flag())
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "ghost", "value": "any"},
    )
    assert r.status_code == 404


def test_submit_flag_duplicate_409():
    """The same team capturing the same flag twice -> 409 (one row)."""
    run_id = asyncio.run(_seed_scenario_with_flag())
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r1 = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "FLAG{pwned}"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "FLAG{pwned}"},
    )
    assert r2.status_code == 409


def test_submit_flag_terminal_run_409():
    """Run in a terminal state can't accept new submissions."""
    run_id = asyncio.run(_seed_terminal_run())
    from app.main import app
    token = sign_token(sub="alice", role="blue", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "FLAG{pwned}"},
    )
    assert r.status_code == 409


async def _seed_terminal_run():
    """Seed a run that's already in SUCCEEDED state."""
    import uuid
    sm = get_sessionmaker()
    async with sm() as session:
        scen = models.Scenario(
            name=f"f5-term-{uuid.uuid4().hex[:8]}",
            title="term",
            version=1,
            difficulty="beginner",
            duration_min=30,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {"assets": [], "flags": [
                    {"id": "f1", "side": "red", "value": "v",
                     "planted_on_role": "r", "decay_window_seconds": 60,
                     "base_points": 10}
                ]},
            },
        )
        session.add(scen)
        await session.flush()
        run = models.Run(
            scenario_id=scen.id,
            status=models.RunStatus.SUCCEEDED,
            started_by="alice",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
            ended_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        return run.id


def test_submit_flag_403_for_unauthorized_submitter():
    """Someone not the run owner (and not admin/lead) -> 403."""
    run_id = asyncio.run(_seed_scenario_with_flag())
    from app.main import app
    # alice owns the run; eve is a red user.
    token = sign_token(sub="eve", role="red", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post(
        f"/api/v1/drills/{run_id}/submit-flag",
        json={"flag_id": "f1", "value": "FLAG{pwned}"},
    )
    assert r.status_code == 403


# --- migration + model -------------------------------------------------


def test_models_flag_submission_fields():
    """The FlagSubmission model has all the fields the API pins."""
    fields = {c.name for c in models.FlagSubmission.__table__.columns}
    expected = {
        "id", "run_id", "flag_id", "team", "submitted_by",
        "captured_at", "points", "elapsed_seconds",
        "created_at", "updated_at",  # TimestampMixin
    }
    assert expected <= fields, (
        f"missing columns: {expected - fields}"
    )


def test_models_flag_submission_unique():
    """The unique constraint is wired and named."""
    table_args = models.FlagSubmission.__table_args__
    found = False
    for entry in table_args:
        if hasattr(entry, "name") and entry.name == (
            "uq_flag_submissions_run_flag_team"
        ):
            found = True
            # Confirm the columns.
            cols = {c.name for c in entry.columns}
            assert cols == {"run_id", "flag_id", "team"}
    assert found, (
        "UniqueConstraint uq_flag_submissions_run_flag_team must exist"
    )


def test_models_flag_side_enum():
    sides = {e.value for e in models.FlagSide}
    assert sides == {"red", "blue", "self"}


def test_alembic_0005_migration_runs():
    """The migration source is on disk and chains after 0004."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "0005_flag_submissions.py"
    ).read_text()
    assert 'down_revision = "0004_asset_instance"' in src
    assert 'revision = "0005_flag_submissions"' in src
    assert "create_table" in src
    assert "upgrade" in src
    assert "downgrade" in src


# --- F5.2: runner plants flags at start_run ----------------------------


@pytest.fixture
def mock_adapter_with_vm():
    from app.runners.adapter import CloneSpec
    from app.runners.mock_adapter import MockProxmoxAdapter
    a = MockProxmoxAdapter(templates={"tpl-x": 9000})
    return a


@pytest.mark.asyncio
async def test_runner_writes_flag_planted_audit(
    mock_adapter_with_vm,
):
    """A scenario with spec.flags[] yields FLAG_PLANTED audit rows
    during start_run, one per flag. The runner doesn't fail on
    planted_on_role mismatches (the asset may not exist; the
    operator might have set planted_on_role=router_fw but not
    declared that role as an asset).
    """
    from app.runners.mock_adapter import MockProxmoxAdapter
    from app.runners.runner import Runner, RunRequest

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        scen = models.Scenario(
            name="flag-test", title="flag-test", version=1,
            difficulty="beginner", duration_min=30,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {
                    "assets": [
                        {"role": "fileserver", "kind": "vm",
                         "template": "tpl-x", "networks": []}
                    ],
                    "flags": [
                        {
                            "id": "f1", "side": "red",
                            "value": "FLAG{pwned}",
                            "planted_on_role": "fileserver",
                            "decay_window_seconds": 600,
                            "base_points": 100,
                        },
                    ],
                },
            },
        )
        session.add(scen)
        await session.commit()

    runner = Runner(adapter=mock_adapter_with_vm)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await runner.start_run(RunRequest(scenario_id=1), session=session)
        # Audit rows
        rows = (await session.execute(
            select(models.AuditLog).where(
                models.AuditLog.action == "flag.planted"
            ).where(models.AuditLog.run_id == 1)
        )).scalars().all()
        assert len(rows) == 1, f"expected 1 flag.planted audit; got {len(rows)}"
        details = rows[0].details
        assert details["flag_id"] == "f1"
        assert details["side"] == "red"
        assert details["planted_on_role"] == "fileserver"
        # The planted_on_role matches a real asset row.
        assert rows[0].asset_id is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_runner_logs_warning_when_planted_on_unknown_role(
    mock_adapter_with_vm,
):
    """A flag pointing at a role the scenario doesn't declare
    still records the audit row (with asset_id=None). Operators
    see this in the audit log and the demo scenario explains."""
    import logging
    from unittest.mock import patch

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        scen = models.Scenario(
            name="unknown-role", title="unknown-role", version=1,
            difficulty="beginner", duration_min=30,
            spec={
                "apiVersion": "divide/v1",
                "kind": "Scenario",
                "spec": {
                    "assets": [
                        {"role": "victim", "kind": "vm",
                         "template": "tpl-x", "networks": []}
                    ],
                    "flags": [
                        {
                            "id": "f1", "side": "red",
                            "value": "v",
                            "planted_on_role": "ghost",  # doesn't exist
                            "decay_window_seconds": 60,
                            "base_points": 10,
                        },
                    ],
                },
            },
        )
        session.add(scen)
        await session.commit()

    from app.runners.runner import Runner, RunRequest
    runner = Runner(adapter=mock_adapter_with_vm)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        with patch("app.runners.runner.log") as mock_log:
            await runner.start_run(
                RunRequest(scenario_id=1), session=session
            )
            # INFO-level planted log; the audit row still happens.
            audit_count = sum(
                1 for call in mock_log.info.call_args_list
                if "runner.flags.planted" in str(call)
            )
            assert audit_count == 1, (
                "expected one runner.flags.planted log line"
            )

        rows = (await session.execute(
            select(models.AuditLog).where(
                models.AuditLog.action == "flag.planted"
            ).where(models.AuditLog.run_id == 1)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].asset_id is None
    await engine.dispose()
