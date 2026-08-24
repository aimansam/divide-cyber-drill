"""Tests for docs/F5-SCORING.md.

The F5 runbook documents the scoring formula + endpoint contract.
These tests pin the runbook so future plans that change the
scoring logic (or the endpoint shape) force an update here.
"""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F5-SCORING.md"
DEMO_YAML = REPO / "examples" / "scenarios" / "red-vs-blue-baseline.scenario.yaml"
SCHEMA = REPO / "schemas" / "scenario.schema.json"


def _read_runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file existence + TL;DR ---------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F5-SCORING.md is missing"


def test_runbook_has_tldr():
    assert "TL;DR" in _read_runbook()


def test_runbook_references_f5_commits():
    """F5 commits must be cited so readers can cross-check the code."""
    src = _read_runbook()
    assert "98e4e7c" in src and "85ecf29" in src, (
        "F5-SCORING.md must reference its own commits"
    )


# --- scoring formula -----------------------------------------------------


def test_runbook_pins_the_scoring_formula():
    """The exact scoring formula must be present in the runbook."""
    src = _read_runbook()
    assert "floor" in src.lower()
    assert "1 - elapsed / window" in src


def test_runbook_pins_zero_window_baseline():
    """The runbook must surface the no-decay edge case."""
    src = _read_runbook()
    assert "t=0" in src
    assert "window" in src.lower()


def test_runbook_pins_run_audit_action_flag_planted():
    """The runner integration logs a 'flag.planted' audit row."""
    src = _read_runbook()
    assert "flag.planted" in src or "FLAG_PLANTED" in src


def test_runbook_documents_no_value_in_audit():
    """The audit row never contains the flag value (security pin)."""
    src = _read_runbook()
    assert "value_present" in src
    assert "value is **never** in the audit log" in src or "never logs" in src.lower()


# --- endpoint contract --------------------------------------------------


def test_runbook_documents_submit_flag_endpoint():
    """POST /api/v1/drills/{id}/submit-flag must be documented."""
    src = _read_runbook()
    assert "/api/v1/drills/{id}/submit-flag" in src or (
        "/drills/{id}/submit-flag" in src
    )


def test_runbook_documents_error_codes():
    """The 5 error codes must be documented (422, 404, 409, etc.)."""
    src = _read_runbook()
    for code in ("422", "404", "409"):
        assert code in src


def test_runbook_documents_rbac_matrix():
    """Five roles, three RBAC columns."""
    src = _read_runbook()
    for role in ("admin", "lead", "red", "blue", "observer"):
        assert role in src


# --- demo scenario parity ----------------------------------------------


def test_runbook_links_to_demo_scenario():
    src = _read_runbook()
    assert "red-vs-blue-baseline" in src


def test_demo_scenario_declares_three_flags():
    """The cyber-range scenario declares 3 flags in spec.flags[]."""
    spec = yaml.safe_load(DEMO_YAML.read_text())
    flags = spec["spec"].get("flags") or []
    assert len(flags) == 3, (
        f"red-vs-blue-baseline should declare 3 flags; got {len(flags)}"
    )
    # Each has the right shape.
    for f in flags:
        for k in ("id", "side", "value", "planted_on_role",
                  "decay_window_seconds", "base_points"):
            assert k in f, f"flag {f.get('id')!r} missing {k!r}"
    # Sides are all 'red' (the demo plants red-hunted flags).
    sides = {f["side"] for f in flags}
    assert sides == {"red"}


def test_demo_scenario_flags_match_schema():
    """The demo scenario validates against the scenario schema."""
    import json
    from jsonschema import Draft202012Validator

    spec = yaml.safe_load(DEMO_YAML.read_text())
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator(schema).validate(spec)


def test_schema_has_flags_field():
    """The scenario JSON schema declares spec.flags[]."""
    import json
    schema = json.loads(SCHEMA.read_text())
    flags = schema["properties"]["spec"]["properties"].get("flags")
    assert flags is not None, "schema must have spec.flags[]"
    assert flags["type"] == "array"
    # Pin the required fields per item so a future schema change
    # that drops a field fires this test.
    item_required = set(flags["items"]["required"])
    expected = {
        "id", "side", "value", "planted_on_role",
        "decay_window_seconds", "base_points",
    }
    assert expected <= item_required, (
        f"missing flag fields: {expected - item_required}"
    )


# --- what isn't F5 ------------------------------------------------------


def test_runbook_documents_followups():
    """F5 explicitly defers leaderboard/rotation/planting."""
    src = _read_runbook()
    assert "F6" in src  # leaderboard
    assert "F8" in src  # SOC view


def test_runbook_explains_planting_via_cloud_init():
    src = _read_runbook()
    assert "cloud-init" in src.lower() or "user_data" in src.lower()


# --- boundaries ---------------------------------------------------------


def test_runbook_does_not_promise_rotation():
    """F5 explicitly says flag rotation is post-F5."""
    src = _read_runbook()
    assert (
        "rotation" in src.lower()
    ), "runbook should mention rotation is deferred"


def test_runbook_does_not_promise_per_team_scoring():
    """Per-team scoring is F6 not F5."""
    src = _read_runbook()
    assert (
        "F6" in src and ("per-team" in src.lower() or "team-specific" in src.lower())
    ), "runbook should explain per-team scoring is F6"
