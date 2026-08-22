"""Tests for the verify_drill.py CLI helpers.

These verify the JSON-shape tolerance and check functions without
hitting the live API. The actual verify run is exercised by hand
after `make live-drill` against a real PVE -- see
docs/LIVE-DRILL-RUNBOOK.md.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_verify_drill",
        Path(__file__).resolve().parent.parent / "tools" / "verify_drill.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- check_run_status ----------


def test_check_run_status_passes_on_match():
    mod = _load_module()
    ok, detail = mod.check_run_status({"status": "succeeded"}, "succeeded")
    assert ok is True
    assert "succeeded" in detail


def test_check_run_status_fails_on_mismatch():
    mod = _load_module()
    ok, detail = mod.check_run_status({"status": "failed"}, "succeeded")
    assert ok is False
    assert "failed" in detail
    assert "succeeded" in detail


# ---------- check_assets_destroyed ----------


def test_check_assets_destroyed_passes_when_all_stopped():
    mod = _load_module()
    assets = [{"role": "drill_vm", "pve_vmid": 9001, "status": "stopped"}]
    ok, detail = mod.check_assets_destroyed(assets)
    assert ok is True
    assert "9001" in detail


def test_check_assets_destroyed_passes_for_orphaned():
    mod = _load_module()
    assets = [{"role": "drill_vm", "pve_vmid": 9001, "status": "orphaned"}]
    ok, _ = mod.check_assets_destroyed(assets)
    assert ok is True


def test_check_assets_destroyed_fails_when_asset_still_running():
    mod = _load_module()
    assets = [{"role": "drill_vm", "pve_vmid": 9001, "status": "running"}]
    ok, detail = mod.check_assets_destroyed(assets)
    assert ok is False
    assert "drill_vm=running" in detail


def test_check_assets_destroyed_fails_when_no_vmid_recorded():
    mod = _load_module()
    assets = [{"role": "drill_vm", "pve_vmid": None, "status": "stopped"}]
    ok, detail = mod.check_assets_destroyed(assets)
    assert ok is False
    assert "pve_vmid" in detail


def test_check_assets_destroyed_fails_on_empty_list():
    mod = _load_module()
    ok, detail = mod.check_assets_destroyed([])
    assert ok is False
    assert "no assets" in detail


# ---------- check_assets_spawned ----------


def test_check_assets_spawned_passes_when_vmid_present():
    mod = _load_module()
    assets = [{"role": "drill_vm", "pve_vmid": 9001}]
    ok, detail = mod.check_assets_spawned(assets)
    assert ok is True
    assert "9001" in detail


def test_check_assets_spawned_fails_when_no_vmid():
    mod = _load_module()
    ok, detail = mod.check_assets_spawned([{"role": "drill_vm", "pve_vmid": None}])
    assert ok is False
    assert "no asset has pve_vmid" in detail


# ---------- check_audit ----------


def test_check_audit_skips_when_endpoint_unavailable():
    mod = _load_module()
    # Empty actions list = endpoint returned 404.
    ok, detail = mod.check_audit([], "succeeded")
    assert ok is True
    assert "skipping" in detail


def test_check_audit_succeeded_passes_with_started_and_completed():
    mod = _load_module()
    actions = ["run.started", "asset.spawned", "run.completed"]
    ok, _ = mod.check_audit(actions, "succeeded")
    assert ok is True


def test_check_audit_failed_requires_failed_action():
    mod = _load_module()
    ok, detail = mod.check_audit(["run.started"], "failed")
    assert ok is False
    assert "run.failed" in detail


def test_check_audit_cancelled_requires_cancelled_action():
    mod = _load_module()
    ok, detail = mod.check_audit(["run.started"], "cancelled")
    assert ok is False
    assert "run.cancelled" in detail


# ---------- check_metrics_counter ----------


def test_check_metrics_counter_passes_with_active_zero():
    mod = _load_module()
    ok, detail = mod.check_metrics_counter(
        {"divide_runs_total": 3.0, "divide_runs_active": 0}
    )
    assert ok is True
    assert "3.0" in detail


def test_check_metrics_counter_fails_when_metric_missing():
    mod = _load_module()
    ok, detail = mod.check_metrics_counter({"divide_runs_active": 0})
    assert ok is False
    assert "not found" in detail


def test_check_metrics_counter_fails_when_runs_hanging():
    mod = _load_module()
    ok, detail = mod.check_metrics_counter(
        {"divide_runs_total": 5.0, "divide_runs_active": 2}
    )
    assert ok is False
    assert "in-flight" in detail


# ---------- _fetch_metrics: label stripping + parse ----------


def test_fetch_metrics_strips_labels_and_parses_values():
    mod = _load_module()
    from unittest.mock import MagicMock

    sample = (
        "# HELP divide_runs_total X\n"
        "divide_runs_total{adapter=\"real\",outcome=\"succeeded\"} 7.0\n"
        "divide_runs_active 0.0\n"
        "divide_run_duration_seconds_bucket{le=\"+Inf\"} 12.0\n"
    )
    client = MagicMock()
    client.get.return_value.text = sample
    client.get.return_value.raise_for_status = lambda: None

    metrics = mod._fetch_metrics(client)
    assert metrics == {
        "divide_runs_total": 7.0,
        "divide_runs_active": 0.0,
        "divide_run_duration_seconds_bucket": 12.0,
    }


def test_fetch_metrics_skips_unparseable_lines():
    mod = _load_module()
    from unittest.mock import MagicMock

    sample = (
        "divide_runs_total 1.0\n"
        "divide_runs_active not_a_number\n"
        "divide_runs_active 0.0\n"
    )
    client = MagicMock()
    client.get.return_value.text = sample
    client.get.return_value.raise_for_status = lambda: None

    metrics = mod._fetch_metrics(client)
    assert metrics["divide_runs_total"] == 1.0
    assert metrics["divide_runs_active"] == 0.0


# ---------- _fetch_run: list-shape tolerance ----------


def test_fetch_run_finds_run_in_items_wrapper():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = {
        "items": [
            {"run_id": 5, "status": "failed"},
            {"run_id": 6, "status": "succeeded"},
        ],
        "total": 2,
    }
    client.get.return_value.raise_for_status = lambda: None

    data = mod._fetch_run(client, 6)
    assert data is not None
    assert data["run"]["status"] == "succeeded"
    assert data["assets"] == []  # not exposed by list endpoint


def test_fetch_run_finds_run_in_bare_list():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = [
        {"run_id": 5, "status": "failed"},
    ]
    client.get.return_value.raise_for_status = lambda: None

    data = mod._fetch_run(client, 5)
    assert data is not None
    assert data["run"]["status"] == "failed"


def test_fetch_run_returns_none_when_id_absent():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = {"items": [{"run_id": 5}]}
    client.get.return_value.raise_for_status = lambda: None

    assert mod._fetch_run(client, 99) is None


