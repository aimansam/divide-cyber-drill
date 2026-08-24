"""F8: SOC view (TelemetryEvent model + ingestion + recent).

Three surfaces:

  * TelemetryEvent model -- 4 tests
  * EventBus pub/sub (recent / subscribe / dedup) -- 6 tests
  * HTTP endpoints (POST /runs/{id}/events + GET history) -- 6 tests

Total: 16 tests.

F8.2 (SSE) and F8.3 (SOC UI + runbook) are separate test files.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth import sign_token
from app.db import models
from app.db.session import get_sessionmaker
from app.services.event_bus import bus, reset_for_tests


# --- model -------------------------------------------------------------


def test_models_telemetry_event_columns():
    cols = {c.name for c in models.TelemetryEvent.__table__.columns}
    expected = {
        "id", "run_id", "asset_id", "ts", "source",
        "kind", "severity", "payload",
        "created_at", "updated_at",
    }
    assert expected <= cols, f"missing: {expected - cols}"


def test_models_telemetry_event_has_ts_index():
    """(run_id, ts) composite index -- the SOC view's hot path."""
    table_args = models.TelemetryEvent.__table_args__
    found = False
    for entry in table_args:
        if (
            hasattr(entry, "name")
            and entry.name == "ix_telemetry_run_id_ts"
        ):
            found = True
            cols = {c.name for c in entry.columns}
            assert cols == {"run_id", "ts"}
    assert found


def test_models_telemetry_event_payload_is_json():
    """payload column is JSON for free-form event data."""
    cols = list(models.TelemetryEvent.__table__.columns)
    payload = next(c for c in cols if c.name == "payload")
    assert "JSON" in str(payload.type).upper()


def test_models_telemetry_severity_enum_values():
    """Severity buckets are exactly: info / low / medium / high."""
    expected = {"info", "low", "medium", "high"}
    actual = {s.value for s in models.TelemetrySeverity}
    assert actual == expected


# --- EventBus pub/sub (in-process) ------------------------------------


def test_bus_publish_and_recent_returns_in_order():
    """publish() inserts at the right; recent() returns ascending."""
    reset_for_tests()
    bus.publish({"id": 1, "kind": "run.started", "run_id": 7})
    bus.publish({"id": 2, "kind": "asset.running", "run_id": 7})
    bus.publish({"id": 3, "kind": "flag.captured", "run_id": 7})
    out = bus.recent(10)
    assert [e["id"] for e in out] == [1, 2, 3]


def test_bus_recent_caps_at_ring_size():
    """Buffer caps at 1024 events; oldest drop out."""
    reset_for_tests()
    for i in range(1100):
        bus.publish({"id": i, "kind": "tick", "run_id": 1})
    out = bus.recent(2000)
    # First 76 dropped, last 1024 retained.
    assert len(out) == 1024
    assert out[0]["id"] == 76
    assert out[-1]["id"] == 1099


def test_bus_publish_dedup_by_id():
    """publish() with the same id is a no-op."""
    reset_for_tests()
    bus.publish({"id": 1, "kind": "x", "run_id": 1})
    bus.publish({"id": 1, "kind": "x", "run_id": 1})
    bus.publish({"id": 1, "kind": "x", "run_id": 1})
    assert len(bus.recent(10)) == 1


def test_bus_publish_no_id_always_inserts():
    """Events without id (custom payloads) are always appended."""
    reset_for_tests()
    for _ in range(5):
        bus.publish({"kind": "tick", "run_id": 1})
    assert len(bus.recent(10)) == 5


def test_bus_subscribe_fan_outs_new_events():
    """Subscribers receive events published after subscribe()."""
    reset_for_tests()

    async def _go():
        q, unsub = bus.subscribe()
        try:
            bus.publish({"id": 1, "kind": "live", "run_id": 1})
            bus.publish({"id": 2, "kind": "live", "run_id": 1})
            e1 = await asyncio.wait_for(q.get(), timeout=0.5)
            e2 = await asyncio.wait_for(q.get(), timeout=0.5)
            assert e1["id"] == 1
            assert e2["id"] == 2
        finally:
            unsub()

    asyncio.run(_go())


def test_bus_unsubscribe_stops_fanout():
    """After unsubscribe(), the subscriber stops receiving."""
    reset_for_tests()

    async def _go():
        q, unsub = bus.subscribe()
        unsub()
        bus.publish({"id": 1, "kind": "live", "run_id": 1})
        # Queue should be empty now.
        try:
            ev = await asyncio.wait_for(q.get(), timeout=0.2)
            raise AssertionError(
                f"got unexpected event after unsubscribe: {ev}"
            )
        except asyncio.TimeoutError:
            pass  # expected

    asyncio.run(_go())


# --- HTTP endpoints ----------------------------------------------------


def _seed_run_in_succeeded_state() -> tuple[int, int]:
    """Seed a scenario + a run for the events endpoints. Returns
    (scenario_id, run_id)."""
    sm = get_sessionmaker()

    async def _seed():
        async with sm() as session:
            scen = models.Scenario(
                name=f"f8-{uuid.uuid4().hex[:8]}",
                title="F8 Test",
                version=1, difficulty="beginner",
                duration_min=30,
                spec={
                    "apiVersion": "divide/v1",
                    "kind": "Scenario",
                    "spec": {"assets": []},
                },
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
            return scen.id, run.id

    return tuple(asyncio.run(_seed()))


def test_admin_injects_event_and_persists():
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    r = admin.post(f"/api/v1/runs/{run_id}/events", json={
        "kind": "kill-chain.signal",
        "severity": "high",
        "payload": {"message": "ssh bruteforce detected"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "kill-chain.signal"
    assert body["severity"] == "high"
    assert body["run_id"] == run_id
    assert body["payload"] == {"message": "ssh bruteforce detected"}


def test_inject_event_requires_admin_or_lead():
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    red = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="alice", role="red", ttl_s=300
        )}
    )
    r = red.post(f"/api/v1/runs/{run_id}/events", json={
        "kind": "x", "severity": "info",
    })
    assert r.status_code in (401, 403)


def test_inject_event_rejects_bad_severity():
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    r = admin.post(f"/api/v1/runs/{run_id}/events", json={
        "kind": "x", "severity": "ultra-critical",
    })
    assert r.status_code == 422


def test_inject_event_rejects_unknown_run():
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    r = admin.post("/api/v1/runs/99999/events", json={
        "kind": "x", "severity": "info",
    })
    assert r.status_code == 404


def test_list_events_returns_history():
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    for k in ("a", "b", "c"):
        admin.post(f"/api/v1/runs/{run_id}/events", json={
            "kind": k, "severity": "info",
        })
    r = admin.get(f"/api/v1/runs/{run_id}/events")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert [e["kind"] for e in body["items"]] == ["a", "b", "c"]


def test_list_events_severity_filter():
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    for sev in ("info", "low", "high", "info"):
        admin.post(f"/api/v1/runs/{run_id}/events", json={
            "kind": "tick", "severity": sev,
        })
    r = admin.get(
        f"/api/v1/runs/{run_id}/events?severity=high"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["severity"] == "high"


def test_inject_event_fans_out_to_bus():
    """After POST /runs/{id}/events, the bus ring buffer has the
    serialized event."""
    reset_for_tests()
    scenario_id, run_id = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    admin.post(f"/api/v1/runs/{run_id}/events", json={
        "kind": "fanout-test",
        "severity": "info",
        "payload": {"x": 1},
    })
    recent = bus.recent(10)
    matching = [
        e for e in recent
        if e.get("kind") == "fanout-test"
        and e.get("run_id") == run_id
    ]
    assert len(matching) == 1
    assert matching[0]["payload"] == {"x": 1}


def test_recent_endpoint_filters_by_run_id():
    """bus.recent() returns ALL events; the /recent endpoint
    filters to the requested run only."""
    reset_for_tests()
    scenario_id_a, run_a = _seed_run_in_succeeded_state()
    scenario_id_b, run_b = _seed_run_in_succeeded_state()
    from app.main import app
    admin = TestClient(
        app, headers={"X-Divide-Token": sign_token(
            sub="root", role="admin", ttl_s=300
        )}
    )
    admin.post(f"/api/v1/runs/{run_a}/events", json={
        "kind": "only-a", "severity": "info",
    })
    admin.post(f"/api/v1/runs/{run_b}/events", json={
        "kind": "only-b", "severity": "info",
    })
    r = admin.get(f"/api/v1/runs/{run_a}/events/recent?n=50")
    body = r.json()
    kinds = [e["kind"] for e in body["items"]]
    assert "only-a" in kinds
    assert "only-b" not in kinds
