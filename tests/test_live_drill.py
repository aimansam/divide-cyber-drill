"""Tests for the live_drill.py CLI helpers.

These verify the JSON-shape tolerance without hitting the live API.
The actual live drill is exercised by `make live-drill` against a real
PVE with PVEVMAdmin privileges — see README.md §8.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_live_drill", Path(__file__).resolve().parent.parent / "tools" / "live_drill.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_scenarios_tolerates_items_wrapper():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.json.return_value = {
        "items": [{"name": "x", "id": 1, "archived_at": None}],
        "total": 1,
    }
    client.get.return_value.raise_for_status = lambda: None

    out = mod._list_scenarios(client)
    assert isinstance(out, list)
    assert out[0]["name"] == "x"


def test_list_scenarios_tolerates_bare_list():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.json.return_value = [
        {"name": "y", "id": 2, "archived_at": None}
    ]
    client.get.return_value.raise_for_status = lambda: None

    out = mod._list_scenarios(client)
    assert isinstance(out, list)
    assert out[0]["name"] == "y"


def test_list_runs_tolerates_items_wrapper_and_uses_run_id():
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.json.return_value = {
        "items": [{"run_id": 7, "status": "succeeded", "scenario_id": 1}],
        "total": 1,
    }
    client.get.return_value.raise_for_status = lambda: None

    out = mod._list_runs(client)
    assert out[0]["run_id"] == 7


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_wait_for_terminal_detects_each_terminal_status(status):
    mod = _load_module()
    from unittest.mock import MagicMock

    client = MagicMock()
    client.get.return_value.json.return_value = {
        "items": [{"run_id": 99, "status": status, "scenario_id": 1}]
    }
    client.get.return_value.raise_for_status = lambda: None

    final = mod._wait_for_terminal(client, 99, timeout_s=2.0, poll_s=0.1)
    assert final is not None
    assert final["status"] == status
