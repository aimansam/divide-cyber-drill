"""Tests for tools/watch_drill.py — no live calls, uses httpx MockTransport."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx


def _load_module():
    if "watch_drill" in sys.modules:
        del sys.modules["watch_drill"]
    spec = importlib.util.spec_from_file_location(
        "watch_drill",
        Path(__file__).resolve().parent.parent / "tools" / "watch_drill.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["watch_drill"] = mod
    spec.loader.exec_module(mod)
    return mod


def _patch_transport(monkeypatch, handlers):
    def _route(request):
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


# --- baseline + success detection ---------------------------------------


def test_baseline_zero_then_increment_detects_success(monkeypatch):
    state = {"value": 0.0}

    def prom_query(req):
        state["value"] += 1.0  # simulate a successful run landing
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {"metric": {"outcome": "succeeded"}, "value": [0, str(state["value"])]}
                    ]
                },
            },
        )

    handlers = {"http://localhost:9090/api/v1/query": prom_query}
    _patch_transport(monkeypatch, handlers)

    mod = _load_module()
    monkeypatch.setattr(
        sys, "argv", ["watch_drill.py", "--timeout", "10", "--poll", "1"]
    )
    rc = mod.main()
    assert rc == 0


# --- api-poll fallback -------------------------------------------------


def test_api_poll_fallback_works(monkeypatch):
    """API poll mode should exit 0 when the latest run is succeeded."""
    # First poll: running. Second poll: succeeded. Watcher detects the
    # change via rid+status comparison.
    poll_count = {"n": 0}

    def list_drills(req):
        poll_count["n"] += 1
        status = "succeeded" if poll_count["n"] >= 2 else "running"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"run_id": 99, "scenario_id": 3, "status": status},
                ]
            },
        )

    handlers = {"http://localhost:8000/api/v1/drills": list_drills}
    _patch_transport(monkeypatch, handlers)
    mod = _load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watch_drill.py",
            "--api-poll",
            "--outcome",
            "succeeded",
            "--timeout",
            "10",
            "--poll",
            "1",
        ],
    )
    rc = mod.main()
    assert rc == 0
    assert poll_count["n"] >= 2


# --- prometheus unreachable falls back to API polling -------------------


def test_prom_unreachable_falls_back_to_api_poll(monkeypatch):
    handlers = {
        "http://localhost:9090/api/v1/query": lambda r: httpx.Response(
            503, json={"status": "error", "error": "unreachable"}
        ),
        "http://localhost:8000/api/v1/drills": lambda r: httpx.Response(
            200,
            json={"items": [{"run_id": 7, "scenario_id": 1, "status": "succeeded"}]},
        ),
    }
    _patch_transport(monkeypatch, handlers)
    mod = _load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watch_drill.py",
            "--outcome",
            "succeeded",
            "--timeout",
            "5",
            "--poll",
            "1",
        ],
    )
    rc = mod.main()
    assert rc == 0


# --- cancel after N ----------------------------------------------------


def test_cancel_after_sends_cancel_request(monkeypatch):
    """When --cancel-after fires, the watcher POSTs /cancel."""
    cancel_calls = []

    def cancel(req):
        cancel_calls.append(req)
        return httpx.Response(
            200,
            json={"run_id": 99, "status": "cancelled", "reason": "user-requested"},
        )

    def prom_query(req):
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {"metric": {"outcome": "cancelled"}, "value": [0, "0.0"]}
                    ]
                },
            },
        )

    def list_drills(req):
        return httpx.Response(
            200, json={"items": [{"run_id": 99, "scenario_id": 3, "status": "running"}]}
        )

    # Important: more specific routes MUST come first. startswith
    # routing would otherwise match /drills/99/cancel against /drills.
    handlers = {
        "http://localhost:8000/api/v1/drills/99/cancel": cancel,
        "http://localhost:8000/api/v1/drills": list_drills,
        "http://localhost:9090/api/v1/query": prom_query,
    }
    _patch_transport(monkeypatch, handlers)

    mod = _load_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watch_drill.py",
            "--cancel-after",
            "1",
            "--outcome",
            "cancelled",
            "--timeout",
            "10",
            "--poll",
            "1",
        ],
    )
    rc = mod.main()
    assert len(cancel_calls) >= 1, "expected cancel POST to have been issued"
    # rc could be 0 (cancelled detected via the counter) or 1 (timeout
    # via the api-poll fallback path) — both prove the cancel was issued.
    assert rc in (0, 1)
