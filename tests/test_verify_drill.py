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


# ---------- check_metrics_counter (label-aware) ----------


def _metric(name: str, value: float, **labels: str) -> dict:
    """Helper to build a single-entry metrics dict.

    Returns ``{ (name, frozenset(labels)): value }`` so tests can splat
    them together: ``metrics = {**_metric("x", 1.0, k="v"), **_metric("y", 2.0)}``.
    """
    return {(name, frozenset(labels.items())): value}


def test_check_metrics_counter_passes_when_expected_outcome_seen():
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 3.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_active", 0.0, adapter="real"),
    }
    ok, detail = mod.check_metrics_counter(metrics, expect="succeeded")
    assert ok is True
    assert "outcome=" in detail and "succeeded" in detail
    assert "3.0" in detail


def test_check_metrics_counter_fails_when_metric_missing():
    mod = _load_module()
    ok, detail = mod.check_metrics_counter({}, expect="succeeded")
    assert ok is False
    assert "0" in detail or "absent" in detail


def test_check_metrics_counter_fails_when_active_nonzero():
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 1.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_active", 2.0, adapter="real"),
    }
    ok, detail = mod.check_metrics_counter(metrics, expect="succeeded")
    assert ok is False
    assert "in-flight" in detail


def test_check_metrics_counter_fails_when_failed_counter_nonzero():
    """The new behavior: failed>0 is a regression signal."""
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 0.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_total", 2.0, outcome="failed", adapter="real"),
        **_metric("divide_runs_active", 0.0, adapter="real"),
    }
    ok, detail = mod.check_metrics_counter(metrics, expect="succeeded")
    assert ok is False
    assert "failed" in detail.lower()


def test_check_metrics_counter_falls_back_to_all_adapters_when_real_missing():
    """If adapter=real has no samples, sum across all adapters."""
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 1.0, outcome="succeeded", adapter="mock"),
        **_metric("divide_runs_active", 0.0, adapter="real"),
    }
    ok, detail = mod.check_metrics_counter(metrics, expect="succeeded")
    assert ok is True
    assert "1.0" in detail


def test_check_metrics_counter_ignores_mock_adapter_for_failure_check():
    """Mock adapter failures shouldn't fail the real-drill check."""
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 5.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_total", 99.0, outcome="failed", adapter="mock"),
        **_metric("divide_runs_active", 0.0, adapter="real"),
    }
    ok, _ = mod.check_metrics_counter(metrics, expect="succeeded")
    assert ok is True



# ---------- _fetch_metrics: label-preserving parse ----------


def test_fetch_metrics_preserves_labels():
    mod = _load_module()
    from unittest.mock import MagicMock

    sample = (
        '# HELP divide_runs_total X\n'
        'divide_runs_total{adapter="real",outcome="succeeded"} 7.0\n'
        'divide_runs_active{adapter="real"} 0.0\n'
        'divide_run_duration_seconds_bucket{le="+Inf"} 12.0\n'
        'divide_runs_total_unlabeled 5.0\n'
    )
    client = MagicMock()
    client.get.return_value.text = sample
    client.get.return_value.raise_for_status = lambda: None
    metrics = mod._fetch_metrics(client)

    # Labeled samples carry their labels.
    assert mod._get_metric(metrics, "divide_runs_total",
                           outcome="succeeded", adapter="real") == 7.0
    assert mod._get_metric(metrics, "divide_runs_active",
                           adapter="real") == 0.0
    # Histogram bucket le=+Inf preserved.
    assert mod._get_metric(metrics, "divide_run_duration_seconds_bucket",
                           le="+Inf") == 12.0
    # Unlabeled sample has empty label set.
    assert mod._get_metric(metrics, "divide_runs_total_unlabeled") == 5.0


def test_fetch_metrics_skips_unparseable_lines():
    mod = _load_module()
    from unittest.mock import MagicMock

    sample = (
        'divide_runs_total 1.0\n'
        'divide_runs_active not_a_number\n'
        'divide_runs_active 0.0\n'
    )
    client = MagicMock()
    client.get.return_value.text = sample
    client.get.return_value.raise_for_status = lambda: None

    metrics = mod._fetch_metrics(client)
    assert mod._get_metric(metrics, "divide_runs_total") == 1.0
    assert mod._get_metric(metrics, "divide_runs_active") == 0.0


# ---------- _get_metric / _sum_metric ----------


def test_get_metric_finds_exact_label_combo():
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 7.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_total", 0.0, outcome="failed", adapter="real"),
    }
    assert mod._get_metric(metrics, "divide_runs_total", outcome="succeeded") == 7.0
    assert mod._get_metric(metrics, "divide_runs_total", outcome="failed") == 0.0


def test_get_metric_treats_extra_labels_as_match():
    """Asking for outcome='succeeded' should match the real counter
    even though it also has adapter='real'."""
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 7.0, outcome="succeeded", adapter="real"),
    }
    assert mod._get_metric(metrics, "divide_runs_total", outcome="succeeded") == 7.0


def test_get_metric_returns_none_when_label_mismatch():
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 7.0, outcome="succeeded", adapter="real"),
    }
    assert mod._get_metric(metrics, "divide_runs_total", outcome="cancelled") is None


def test_sum_metric_aggregates_across_adapters():
    mod = _load_module()
    metrics = {
        **_metric("divide_runs_total", 3.0, outcome="succeeded", adapter="real"),
        **_metric("divide_runs_total", 2.0, outcome="succeeded", adapter="mock"),
    }
    assert mod._sum_metric(metrics, "divide_runs_total", outcome="succeeded") == 5.0


# ---------- _parse_labels ----------


def test_parse_labels_simple():
    mod = _load_module()
    lab = mod._parse_labels('adapter="real",outcome="succeeded"')
    assert ("adapter", "real") in lab
    assert ("outcome", "succeeded") in lab


def test_parse_labels_handles_quoted_commas():
    """If a label value contains a comma, the split must respect quotes."""
    mod = _load_module()
    lab = mod._parse_labels('msg="hello, world",k="v"')
    assert ("msg", "hello, world") in lab
    assert ("k", "v") in lab


def test_parse_labels_handles_empty():
    mod = _load_module()
    assert mod._parse_labels("") == frozenset()


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


