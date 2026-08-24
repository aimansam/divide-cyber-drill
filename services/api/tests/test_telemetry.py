"""Tests for the telemetry sink dispatcher (L2 2.11).

Telemetry is best-effort: a failing sink (e.g. MinIO down) must NOT
fail the drill run. We test that contract by injecting broken sinks
and confirming dispatch returns gracefully.

What we assert:
  * Empty sink list → empty results, no exceptions.
  * Stdout sink writes the JSON to its logger.
  * MinIO not configured → sink list is empty (or stdout-only).
  * Sink failure → dispatch returns SinkResult(ok=False); the other
    sinks still fire.
  * build_sinks_from_spec() honours the scenario spec.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest


class _CapturingSink:
    """Sink that records every event it receives. For tests."""

    name = "capture"

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class _BoomSink:
    """Sink that always raises. Verifies best-effort behaviour."""

    name = "boom"

    async def send(self, event: dict[str, Any]) -> None:
        raise ConnectionError("warehouse is down")


class _HalfBoomSink:
    """Sink that raises only on the second event."""

    name = "halfboom"

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, event: dict[str, Any]) -> None:
        self.calls += 1
        if self.calls == 2:
            raise ConnectionError("simulated outage on second call")


def test_dispatch_with_empty_sinks_returns_empty_results():
    """An empty sink list is a valid (no-op) dispatch."""
    from app.services.telemetry import dispatch

    async def _go():
        return await dispatch([], {"run_id": 1, "type": "test"})

    results = asyncio.run(_go())
    assert results == []


def test_dispatch_with_one_healthy_sink():
    """One capture sink → one SinkResult(ok=True) + event recorded."""
    cap = _CapturingSink()
    from app.services.telemetry import dispatch

    event = {"run_id": 7, "type": "run.completed", "at": "2026-08-24T00:00:00Z"}

    async def _go():
        return await dispatch([cap], event)

    results = asyncio.run(_go())
    assert len(results) == 1
    assert results[0].sink == "capture"
    assert results[0].ok is True
    assert cap.events == [event]


def test_dispatch_returns_failure_result_but_does_not_raise():
    """A failing sink yields ok=False with the error message; the
    exception does NOT propagate."""
    from app.services.telemetry import dispatch

    async def _go():
        return await dispatch([_BoomSink()], {"run_id": 1})

    results = asyncio.run(_go())
    assert len(results) == 1
    assert results[0].ok is False
    assert "warehouse is down" in (results[0].error or "")


def test_dispatch_failure_on_one_sink_does_not_block_others():
    """Multiple sinks: a failure on one doesn't skip the next."""
    cap_a, cap_b = _CapturingSink(), _CapturingSink()
    boom = _BoomSink()
    from app.services.telemetry import dispatch

    event = {"run_id": 9, "type": "asset.spawned"}

    async def _go():
        return await dispatch([cap_a, boom, cap_b], event)

    results = asyncio.run(_go())
    assert [r.sink for r in results] == ["capture", "boom", "capture"]
    assert [r.ok for r in results] == [True, False, True]
    assert cap_a.events == [event]
    assert cap_b.events == [event]


def test_stdout_sink_writes_json_line(caplog):
    """StdoutSink emits a structured-log JSON line per event."""
    from app.services.telemetry import StdoutSink

    sink = StdoutSink()
    event = {"run_id": 3, "type": "test", "foo": "bar"}

    async def _go():
        await sink.send(event)

    with caplog.at_level(logging.INFO, logger="divide.telemetry.stdout"):
        asyncio.run(_go())

    matched = [
        r for r in caplog.records if r.name == "divide.telemetry.stdout"
    ]
    assert matched, caplog.records
    payload = matched[-1].getMessage()
    assert "run_id" in payload
    assert "test" in payload


def test_build_sinks_with_no_spec_returns_empty_list():
    """A scenario without telemetry.sinks has no additional sinks."""
    from app.services.telemetry import build_sinks_from_spec

    assert build_sinks_from_spec(None) == []
    assert build_sinks_from_spec({}) == []
    assert build_sinks_from_spec({"telemetry": {}}) == []
    assert build_sinks_from_spec({"telemetry": {"sinks": []}}) == []


def test_build_sinks_returns_stdout_when_configured():
    from app.services.telemetry import build_sinks_from_spec

    sinks = build_sinks_from_spec(
        {"telemetry": {"sinks": [{"type": "stdout"}]}}
    )
    assert [s.name for s in sinks] == ["stdout"]


def test_build_sinks_skips_minio_when_package_missing(monkeypatch):
    """Without ``minio-py`` installed, no MinIO sink is built."""
    import app.services.telemetry as t_module
    from app.services.telemetry import build_sinks_from_spec

    # Force the missing-pkg code path by hiding the already-imported
    # ``minio`` module.
    monkeypatch.setattr(t_module, "_MINIO_AVAILABLE", False, raising=False)

    sinks = build_sinks_from_spec(
        {"telemetry": {"sinks": [{"type": "minio", "bucket": "x"}]}}
    )
    assert sinks == []


def test_build_sinks_defers_wazuh_and_misp():
    """wazuh/misp sinks are deferred to L3 — skipped, no exception."""
    from app.services.telemetry import build_sinks_from_spec

    sinks = build_sinks_from_spec(
        {
            "telemetry": {
                "sinks": [
                    {"type": "stdout"},
                    {"type": "wazuh", "endpoint": "https://w.example"},
                    {"type": "misp", "endpoint": "https://m.example"},
                    {"type": "stdout"},
                ]
            }
        }
    )
    assert [s.name for s in sinks] == ["stdout", "stdout"]


def test_build_sinks_logs_unknown_sink_type(caplog):
    from app.services.telemetry import build_sinks_from_spec

    with caplog.at_level(logging.WARNING, logger="app.services.telemetry"):
        sinks = build_sinks_from_spec(
            {"telemetry": {"sinks": [{"type": "definitely-not-real"}]}}
        )
    assert sinks == []
    matched = [r for r in caplog.records if "unknown_sink" in r.getMessage()]
    assert matched


def test_halfboom_sink_recovers_on_subsequent_calls():
    """A sink that intermittently fails still receives later events.

    (Verifies dispatch doesn't permanently 'break' a sink instance.)
    """
    half = _HalfBoomSink()
    cap = _CapturingSink()
    from app.services.telemetry import dispatch

    async def _go():
        for i in range(3):
            await dispatch([half, cap], {"run_id": i, "type": "test"})

    asyncio.run(_go())
    assert half.calls == 3  # not stopped after the boom
    assert len(cap.events) == 3