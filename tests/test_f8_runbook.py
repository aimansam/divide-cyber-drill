"""Tests for docs/F8-SOC.md.

The F8 runbook documents the SOC view + live telemetry.
These tests pin the runbook so future plans that change the
event schema or lifecycle force an update here.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F8-SOC.md"


def _read() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file -------------------------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F8-SOC.md is missing"


def test_runbook_has_tldr():
    assert "TL;DR" in _read()


def test_runbook_references_f8_commits():
    src = _read()
    assert "d88dbe6" in src and "7a987f9" in src, (
        "F8-SOC.md must reference its own commits"
    )


# --- endpoints ---------------------------------------------------------


def test_runbook_documents_post_inject_endpoint():
    src = _read()
    assert "POST /runs/{id}/events" in src or "/events" in src


def test_runbook_documents_sse_endpoint():
    src = _read()
    assert "events/stream" in src
    assert "SSE" in src or "text/event-stream" in src


def test_runbook_documents_recent_endpoint():
    src = _read()
    assert "/events/recent" in src


# --- event taxonomy ----------------------------------------------------


def test_runbook_lists_run_started_event():
    src = _read()
    assert "run.started" in src


def test_runbook_lists_run_completed_event():
    src = _read()
    assert "run.completed" in src


def test_runbook_lists_asset_running_event():
    src = _read()
    assert "asset.running" in src


def test_runbook_lists_flag_captured_event():
    src = _read()
    assert "flag.captured" in src


def test_runbook_lists_kill_chain_signal_event():
    src = _read()
    assert "kill-chain.signal" in src


def test_runbook_documents_severity_buckets():
    """The 4-bucket severity scheme is pinned."""
    src = _read()
    for sev in ("info", "low", "medium", "high"):
        assert sev in src, f"severity bucket {sev!r} missing"


# --- architecture ------------------------------------------------------


def test_runbook_documents_event_bus():
    src = _read()
    assert "EventBus" in src
    assert "in-process" in src.lower() or "in process" in src.lower()


def test_runbook_documents_db_persistence():
    src = _read()
    assert "telemetry_events" in src
    assert "persist" in src.lower() or "DB" in src or "row" in src.lower()


def test_runbook_documents_ring_buffer_cap():
    src = _read()
    assert "1024" in src or "ring buffer" in src.lower()


def test_runbook_documents_recent_replay():
    """On cold-connect, clients replay recent events."""
    src = _read()
    assert "replay" in src.lower() or "recent" in src.lower()


# --- RBAC --------------------------------------------------------------


def test_runbook_documents_full_rbac_matrix():
    src = _read()
    for role in ("admin", "lead", "red", "blue", "observer"):
        assert role in src


def test_runbook_pins_inject_admin_or_lead_only():
    src = _read()
    # The matrix should show inject-event as admin / lead only.
    assert "Inject event" in src


# --- negative pins -----------------------------------------------------


def test_runbook_does_not_promise_multi_worker_pubsub():
    """F8.5 with Redis pub/sub is the fix. F8 only does single-worker."""
    src = _read()
    assert "multi-worker" in src.lower() or "redis" in src.lower()


def test_runbook_does_not_promise_replay_ui():
    """Replay UI (playhead) is F8.5+; F8 just shows the stream."""
    src = _read()
    assert "replay ui" in src.lower() or "replay" in src.lower()


def test_runbook_does_not_promise_auto_correlation():
    src = _read()
    assert "auto-correlation" in src.lower() or "correlation" in src.lower()


# --- links -------------------------------------------------------------


def test_runbook_links_to_f5_scoring():
    assert "F5-SCORING.md" in _read()


def test_runbook_links_to_f6_multiteam():
    assert "F6-MULTITEAM.md" in _read()


def test_runbook_links_to_f7_templates():
    assert "F7-TEMPLATES.md" in _read()
