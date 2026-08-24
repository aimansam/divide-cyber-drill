"""Tests for docs/F6-MULTITEAM.md.

The F6 runbook documents the multi-team exercise lifecycle.
These tests pin the runbook so future plans that change the
score mechanism force an update here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F6-MULTITEAM.md"


def _read() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file -------------------------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F6-MULTITEAM.md is missing"


def test_runbook_has_tldr():
    assert "TL;DR" in _read()


def test_runbook_references_f6_commits():
    src = _read()
    assert "5386096" in src and "d7e69f9" in src, (
        "F6-MULTITEAM.md must reference its own commits"
    )


# --- lifecycle ---------------------------------------------------------


def test_runbook_documents_idle_live_ended_archived_states():
    src = _read()
    for state in ("idle", "live", "ended", "archived"):
        assert state in src, f"runbook missing state {state!r}"


def test_runbook_pins_idle_to_ended_rejection():
    """FSM should reject skipping live."""
    src = _read()
    assert (
        "IDLE -> ENDED" in src or "skipping" in src.lower()
    ), "runbook must explain the FSM"


def test_runbook_pins_team_score_increment():
    """On flag capture, team.score is bumped."""
    src = _read()
    assert "team.score" in src


def test_runbook_documents_run_exercise_id_team_columns():
    """Run.exercise_id and Run.team are new in F6."""
    src = _read()
    assert "run.exercise_id" in src or "exercise_id" in src
    assert "run.team" in src or "team" in src


# --- RBAC --------------------------------------------------------------


def test_runbook_documents_full_rbac_matrix():
    src = _read()
    for role in ("admin", "lead", "red", "blue", "observer"):
        assert role in src


# --- endpoint contract --------------------------------------------------


def test_runbook_documents_leaderboard_endpoint():
    src = _read()
    assert "/leaderboard" in src


def test_runbook_documents_members_endpoint():
    src = _read()
    assert "/members" in src


def test_runbook_documents_state_endpoints():
    """The start / stop / archive endpoints are present."""
    src = _read()
    for verb in ("start", "stop", "archive"):
        assert f"/{verb}" in src, f"/{verb} endpoint not in runbook"


# --- what's NOT in F6 --------------------------------------------------


def test_runbook_documents_followups():
    """F6 explicitly defers per-team run visibility + replay + rotation."""
    src = _read()
    # F8 + F6.5 are mentioned
    assert "F8" in src


def test_runbook_links_to_f5_scoring():
    """F6's leaderboard builds on F5's Team.score denormalization."""
    src = _read()
    assert "F5-SCORING.md" in src


def test_runbook_links_to_demo():
    assert "DEMO.md" in _read()


# --- negative pins -----------------------------------------------------


def test_runbook_does_not_promise_replay():
    """Historical replay is F8, not F6. The runbook must surface
    'historical replay' as a follow-up so a future plan adding
    it knows to update the runbook."""
    src = _read()
    assert "replay" in src.lower()


def test_runbook_does_not_promise_per_team_run_visibility_filtering():
    """Same idea for per-team run visibility: deferred."""
    src = _read()
    assert "per-team" in src.lower() or "team-specific" in src.lower()
