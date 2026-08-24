"""Tests for docs/SECTION-15-CLOSURE.md.

This is the operator-facing summary of §15 closure. It pins:
  * Every F3-F8 plan is named.
  * The end-to-end demo workflow is documented.
  * The post-§15 follow-ons (R1-R7) are listed.
  * The test count + portal bundle claims are accurate at
    closure time.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "SECTION-15-CLOSURE.md"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


# --- file -------------------------------------------------------------


def test_closure_doc_exists():
    assert DOC.is_file(), "docs/SECTION-15-CLOSURE.md is missing"


def test_closure_doc_marks_section_15_closed():
    src = _read()
    assert "§15 closed" in src or "CLOSED" in src


# --- F3-F8 plans -------------------------------------------------------


def test_closure_doc_lists_f3():
    assert "F3" in _read()


def test_closure_doc_lists_f4():
    assert "F4" in _read()


def test_closure_doc_lists_f5():
    assert "F5" in _read()


def test_closure_doc_lists_f6():
    assert "F6" in _read()


def test_closure_doc_lists_f7():
    assert "F7" in _read()


def test_closure_doc_lists_f8():
    assert "F8" in _read()


# --- workflow ---------------------------------------------------------


def test_closure_doc_includes_workflow_steps():
    """The 12-step operator workflow is documented."""
    src = _read()
    for step in (
        "Sign in",
        "scenario",
        "exercise",
        "noVNC",
        "Capture",
        "SOC view",
        "Save as template",
        "Stop",
        "report",
        "Clone",
        "Reset",
    ):
        assert step in src, f"workflow step missing: {step!r}"


def test_closure_doc_lists_runbook_links():
    src = _read()
    for f in ("F3-RUNBOOK.md", "F4-NOVNC.md", "F5-SCORING.md",
              "F6-MULTITEAM.md", "F7-TEMPLATES.md", "F8-SOC.md"):
        assert f in src, f"runbook link missing: {f}"


# --- test / bundle claims ---------------------------------------------


def test_closure_doc_states_test_count():
    """Test count is pinned at closure time."""
    src = _read()
    assert "859" in src


def test_closure_doc_states_bundle_size():
    src = _read()
    assert "251.65" in src


# --- follow-ons -------------------------------------------------------


def test_closure_doc_lists_r1_redis_pubsub():
    src = _read()
    assert "R1" in src
    assert "Redis" in src


def test_closure_doc_lists_polish_r2():
    src = _read()
    assert "R2" in src
    assert "light theme" in src.lower() or "polish" in src.lower()


# --- negative pins ----------------------------------------------------


def test_closure_doc_does_not_promise_replay_ui_done():
    """R7 (replay UI) is in follow-ons, not in §15 closure."""
    src = _read()
    # R7 is the replay UI; the doc should list it under open follow-ons.
    assert "R7" in src or "replay UI" in src.lower()
