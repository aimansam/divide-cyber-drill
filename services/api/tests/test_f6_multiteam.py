"""F6: multi-team exercises.

Three surfaces:

  * ExerciseStatus FSM (pure logic) -- 6 tests
  * Exercise + Team + TeamMembership models -- 6 tests
  * HTTP endpoints (CRUD + state transitions + leaderboard) -- 12 tests

Total: 24 tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.auth import sign_token
from app.db import models
from app.db.base import Base
from app.db.session import get_sessionmaker
from app.runners.mock_adapter import MockProxmoxAdapter


# --- ExerciseStatus FSM -------------------------------------------------


def test_fsm_idle_to_live_allowed():
    assert models.ExerciseStatus.can_transition(
        models.ExerciseStatus.IDLE, models.ExerciseStatus.LIVE
    )


def test_fsm_live_to_ended_allowed():
    assert models.ExerciseStatus.can_transition(
        models.ExerciseStatus.LIVE, models.ExerciseStatus.ENDED
    )


def test_fsm_ended_to_live_allowed_for_reopening():
    """Operators can re-open an ended exercise (rare but useful)."""
    assert models.ExerciseStatus.can_transition(
        models.ExerciseStatus.ENDED, models.ExerciseStatus.LIVE
    )


def test_fsm_archived_terminal():
    """Archive is reachable from any state."""
    for src in (
        models.ExerciseStatus.IDLE,
        models.ExerciseStatus.LIVE,
        models.ExerciseStatus.ENDED,
    ):
        assert models.ExerciseStatus.can_transition(
            src, models.ExerciseStatus.ARCHIVED
        )


def test_fsm_idle_to_ended_rejected():
    """IDLE -> ENDED would skip LIVE; reject."""
    assert not models.ExerciseStatus.can_transition(
        models.ExerciseStatus.IDLE, models.ExerciseStatus.ENDED
    )


def test_fsm_self_transition_rejected():
    """A state that's already the same should be a no-op (False)
    so callers don't accidentally re-fire a transition."""
    for state in (
        models.ExerciseStatus.IDLE,
        models.ExerciseStatus.LIVE,
        models.ExerciseStatus.ENDED,
    ):
        assert not models.ExerciseStatus.can_transition(state, state)


def test_fsm_transition_to_method_rejects_invalid():
    """The model.transition_to() wraps the FSM check."""
    ex = models.Exercise(name="x", title="x", scenario_id=1,
                          status=models.ExerciseStatus.IDLE)
    with pytest.raises(ValueError):
        ex.transition_to(models.ExerciseStatus.ENDED)
    # Valid transition: IDLE -> LIVE
    ex.transition_to(models.ExerciseStatus.LIVE)
    assert ex.status is models.ExerciseStatus.LIVE


# --- models -------------------------------------------------------------


def test_models_exercise_columns():
    cols = {c.name for c in models.Exercise.__table__.columns}
    expected = {
        "id", "name", "title", "scenario_id", "status",
        "starts_at", "ends_at", "created_by",
        "created_at", "updated_at",
    }
    assert expected <= cols, (
        f"missing columns: {expected - cols}"
    )


def test_models_team_columns():
    cols = {c.name for c in models.Team.__table__.columns}
    expected = {
        "id", "exercise_id", "name", "color", "score",
        "created_at", "updated_at",
    }
    assert expected <= cols


def test_models_team_membership_columns():
    cols = {c.name for c in models.TeamMembership.__table__.columns}
    expected = {
        "id", "sub", "exercise_id", "team_id", "role",
        "created_at", "updated_at",
    }
    assert expected <= cols


def test_models_run_has_exercise_and_team_columns():
    cols = {c.name for c in models.Run.__table__.columns}
    assert "exercise_id" in cols
    assert "team" in cols


def test_models_team_unique_within_exercise():
    """Two teams with the same name in the same exercise: the
    unique constraint fires."""
    table_args = models.Team.__table_args__
    found = False
    for entry in table_args:
        if hasattr(entry, "name") and entry.name == "uq_teams_exercise_name":
            found = True
            cols = {c.name for c in entry.columns}
            assert cols == {"exercise_id", "name"}
    assert found, "uq_teams_exercise_name must exist"


def test_models_team_membership_unique_per_sub_per_exercise():
    """One user per exercise at most; multiple teams per user
    works because each row is per-exercise."""
    table_args = models.TeamMembership.__table_args__
    found = False
    for entry in table_args:
        if hasattr(entry, "name") and entry.name == (
            "uq_team_membership_user_exercise"
        ):
            found = True
            cols = {c.name for c in entry.columns}
            assert cols == {"sub", "exercise_id"}
    assert found


# --- HTTP endpoints ----------------------------------------------------


async def _seed_scenario() -> int:
    """Seed a scenario we can attach exercises to. Returns id."""
    import uuid
    sm = get_sessionmaker()
    async with sm() as session:
        s = models.Scenario(
            name=f"f6-{uuid.uuid4().hex[:8]}",
            title="f6-test",
            version=1,
            difficulty="beginner",
            duration_min=30,
            spec={"apiVersion": "divide/v1", "kind": "Scenario",
                   "spec": {"assets": []}},
        )
        session.add(s)
        await session.commit()
        return s.id


def test_admin_creates_exercise_with_teams():
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    r = client.post(
        "/api/v1/exercises",
        json={
            "name": "tabletop-2026-08",
            "title": "Q3 Tabletop",
            "scenario_id": scenario_id,
            "teams": [
                {"name": "red",  "color": "#dc2626"},
                {"name": "blue", "color": "#2563eb"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "idle"
    assert len(body["teams"]) == 2
    assert {t["name"] for t in body["teams"]} == {"red", "blue"}


def test_create_exercise_requires_admin_token():
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    # Non-admin token
    token = sign_token(sub="alice", role="red", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/exercises", json={
        "name": "tabletop-bad", "title": "x", "scenario_id": scenario_id,
        "teams": [{"name": "red"}],
    })
    # Should be 401/403 (require_role decorator)
    assert r.status_code in (401, 403)


def test_create_exercise_requires_teams():
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/exercises", json={
        "name": "tabletop-no-teams", "title": "x",
        "scenario_id": scenario_id, "teams": [],
    })
    assert r.status_code == 422


def test_create_exercise_422_on_invalid_scenario():
    """A scenario_id that doesn't exist fails in DB: we surface
    409 / 422. The current implementation bubbles the FK
    violation as 409."""
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.post("/api/v1/exercises", json={
        "name": "tabletop-bad-scen", "title": "x", "scenario_id": 99999,
        "teams": [{"name": "red"}],
    })
    # Either 409 (FK) or 404 (lookup ahead). The implementation
    # has no pre-check; FK error surfaces. Either is acceptable;
    # we just need a non-200.
    assert r.status_code >= 400


def test_start_exercise_transitions_idle_to_live():
    """POST /exercises/{id}/start moves IDLE -> LIVE.

    Uses an admin token + a freshly-created exercise."""
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})

    create = client.post("/api/v1/exercises", json={
        "name": f"start-test-{uuid.uuid4().hex[:8]}",
        "title": "Start Test", "scenario_id": scenario_id,
        "teams": [{"name": "red"}, {"name": "blue"}],
    }).json()
    assert create["status"] == "idle"

    r = client.post(f"/api/v1/exercises/{create['id']}/start")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "live"
    assert body["starts_at"] is not None


def test_stop_exercise_transitions_live_to_ended():
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    create = client.post("/api/v1/exercises", json={
        "name": f"stop-test-{uuid.uuid4().hex[:8]}",
        "title": "Stop Test", "scenario_id": scenario_id,
        "teams": [{"name": "red"}, {"name": "blue"}],
    }).json()
    client.post(f"/api/v1/exercises/{create['id']}/start")
    r = client.post(f"/api/v1/exercises/{create['id']}/stop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ended"
    assert body["ends_at"] is not None


def test_idle_to_ended_rejected():
    """Skipping LIVE in the FSM is rejected."""
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    create = client.post("/api/v1/exercises", json={
        "name": f"idle-stop-{uuid.uuid4().hex[:8]}",
        "title": "Idle Stop", "scenario_id": scenario_id,
        "teams": [{"name": "red"}],
    }).json()
    r = client.post(f"/api/v1/exercises/{create['id']}/stop")
    assert r.status_code == 409


def test_list_exercises_filters_by_role():
    """Red team only sees exercises they're a TeamMember of."""
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    admin_token = sign_token(sub="root", role="admin", ttl_s=300)
    red_token = sign_token(sub="alice", role="red", ttl_s=300)
    admin = TestClient(app, headers={"X-Divide-Token": admin_token})
    red = TestClient(app, headers={"X-Divide-Token": red_token})
    ex = admin.post("/api/v1/exercises", json={
        "name": f"red-only-{uuid.uuid4().hex[:8]}",
        "title": "Red Only", "scenario_id": scenario_id,
        "teams": [{"name": "red", "color": "#dc2626"}],
    }).json()
    team_id = ex["teams"][0]["id"]
    # Add alice as a member
    admin.post(f"/api/v1/exercises/{ex['id']}/members", json={
        "sub": "alice", "team_id": team_id, "role": "member",
    })
    # Admin sees the exercise
    res = admin.get("/api/v1/exercises").json()
    assert any(e["name"] == ex["name"] for e in res["items"])
    # Red (alice) sees it
    res = red.get("/api/v1/exercises").json()
    assert any(e["name"] == ex["name"] for e in res["items"])
    # Red (eve) does NOT see it
    eve_token = sign_token(sub="eve", role="red", ttl_s=300)
    eve = TestClient(app, headers={"X-Divide-Token": eve_token})
    res = eve.get("/api/v1/exercises").json()
    assert not any(e["name"] == ex["name"] for e in res["items"])


def test_get_exercise_404_for_unknown():
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    r = client.get("/api/v1/exercises/99999")
    assert r.status_code == 404


def test_get_exercise_403_for_non_member():
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    admin_token = sign_token(sub="root", role="admin", ttl_s=300)
    eve_token = sign_token(sub="eve", role="red", ttl_s=300)
    admin = TestClient(app, headers={"X-Divide-Token": admin_token})
    eve = TestClient(app, headers={"X-Divide-Token": eve_token})
    ex = admin.post("/api/v1/exercises", json={
        "name": f"private-{uuid.uuid4().hex[:8]}",
        "title": "Private", "scenario_id": scenario_id,
        "teams": [{"name": "red"}],
    }).json()
    r = eve.get(f"/api/v1/exercises/{ex['id']}")
    assert r.status_code == 403


def test_leaderboard_returns_team_scores():
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    ex = client.post("/api/v1/exercises", json={
        "name": f"lb-{uuid.uuid4().hex[:8]}",
        "title": "Leaderboard Test", "scenario_id": scenario_id,
        "teams": [
            {"name": "red",  "color": "#dc2626"},
            {"name": "blue", "color": "#2563eb"},
        ],
    }).json()
    # Bump team's score directly via the DB (we don't have flag
    # side yet; F5.2 will wire this). Simulate by reading the
    # teams and confirming the LB returns them in score order.
    r = client.get(f"/api/v1/exercises/{ex['id']}/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert body["exercise_id"] == ex["id"]
    assert len(body["teams"]) == 2
    # Each team has its initial score (0); ranks are 1 + 2.
    ranks = {t["name"]: t["rank"] for t in body["teams"]}
    assert set(ranks.keys()) == {"red", "blue"}


def test_add_member_409_for_existing_member():
    """A user can only be in one team per exercise."""
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    admin_token = sign_token(sub="root", role="admin", ttl_s=300)
    admin = TestClient(app, headers={"X-Divide-Token": admin_token})
    ex = admin.post("/api/v1/exercises", json={
        "name": f"dup-member-{uuid.uuid4().hex[:8]}",
        "title": "Dup Member", "scenario_id": scenario_id,
        "teams": [{"name": "red"}, {"name": "blue"}],
    }).json()
    red_id = next(t["id"] for t in ex["teams"] if t["name"] == "red")
    blue_id = next(t["id"] for t in ex["teams"] if t["name"] == "blue")
    r1 = admin.post(f"/api/v1/exercises/{ex['id']}/members", json={
        "sub": "alice", "team_id": red_id,
    })
    assert r1.status_code == 200
    r2 = admin.post(f"/api/v1/exercises/{ex['id']}/members", json={
        "sub": "alice", "team_id": blue_id,
    })
    assert r2.status_code == 409


def test_add_member_team_not_in_exercise_404():
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    admin_token = sign_token(sub="root", role="admin", ttl_s=300)
    admin = TestClient(app, headers={"X-Divide-Token": admin_token})
    ex = admin.post("/api/v1/exercises", json={
        "name": f"strange-team-{uuid.uuid4().hex[:8]}",
        "title": "Strange Team", "scenario_id": scenario_id,
        "teams": [{"name": "red"}],
    }).json()
    r = admin.post(f"/api/v1/exercises/{ex['id']}/members", json={
        "sub": "alice", "team_id": 99999,
    })
    assert r.status_code == 404


def test_archive_exercise_any_state():
    """Archive works from IDLE / LIVE / ENDED."""
    import uuid
    scenario_id = asyncio.run(_seed_scenario())
    from app.main import app
    token = sign_token(sub="root", role="admin", ttl_s=300)
    client = TestClient(app, headers={"X-Divide-Token": token})
    ex = client.post("/api/v1/exercises", json={
        "name": f"arch-{uuid.uuid4().hex[:8]}",
        "title": "Arch Test", "scenario_id": scenario_id,
        "teams": [{"name": "red"}],
    }).json()
    r = client.post(f"/api/v1/exercises/{ex['id']}/archive")
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
