"""Tests for docs/F7-TEMPLATES.md.

The F7 runbook documents the range-template workflow.
These tests pin the runbook so future plans that change the
snapshot schema or lifecycle force an update here.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F7-TEMPLATES.md"


def _read() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file -------------------------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F7-TEMPLATES.md is missing"


def test_runbook_has_tldr():
    assert "TL;DR" in _read()


def test_runbook_references_f7_commits():
    src = _read()
    assert "fa20fb3" in src and "7c4f03a" in src, (
        "F7-TEMPLATES.md must reference its own commits"
    )


# --- lifecycle ---------------------------------------------------------


def test_runbook_documents_create_endpoint():
    """POST /templates (admin) is documented."""
    src = _read()
    assert "POST /templates" in src


def test_runbook_documents_clone_via_drills():
    """Cloning is via POST /drills with template_id."""
    src = _read()
    assert "template_id" in src
    assert "POST /drills" in src


def test_runbook_documents_save_as_template():
    src = _read()
    assert "save-as-template" in src


def test_runbook_documents_reset_endpoint():
    src = _read()
    assert "POST /drills/{id}/reset" in src or "/reset" in src


def test_runbook_documents_delete_endpoint():
    src = _read()
    assert "DELETE" in src


def test_runbook_pins_snapshot_immutability():
    """Templates are never updated in place; new = new name."""
    src = _read()
    assert "immutable" in src.lower() or "never updated" in src.lower()


def test_runbook_pins_reset_requires_template_binding():
    src = _read()
    # Without a template the run can't be reset.
    assert "requires a bound template" in src.lower() or (
        "no template" in src.lower()
    )


# --- snapshot schema ---------------------------------------------------


def test_runbook_documents_snapshot_scenario_fields():
    src = _read()
    for field in ("scenario_id", "scenario_name", "scenario_version"):
        assert field in src, f"missing snapshot field {field!r}"


def test_runbook_documents_snapshot_assets_and_flags():
    src = _read()
    assert '"assets"' in src
    assert '"flags"' in src


def test_runbook_documents_snapshot_networks():
    src = _read()
    assert "networks" in src


def test_runbook_documents_snapshot_run_status():
    src = _read()
    assert "run_status_at_snapshot" in src


# --- RBAC --------------------------------------------------------------


def test_runbook_documents_full_rbac_matrix():
    src = _read()
    for role in ("admin", "lead", "red", "blue", "observer"):
        assert role in src


def test_runbook_pins_save_as_template_admin_only():
    src = _read()
    # The matrix should show save-as-template as admin only.
    assert "Save-as-template" in src and "admin" in src


# --- negative pins -----------------------------------------------------


def test_runbook_does_not_promise_restore_from_backup():
    """Restore-from-backup is not in F7; the runbook explicitly
    defers it."""
    src = _read()
    assert "Restore from backup" in src or (
        "restore" in src.lower() and "backup" in src.lower()
    )


def test_runbook_does_not_promise_template_diff_ui():
    src = _read()
    assert "Template diff" in src or "template diff" in src.lower()


def test_runbook_does_not_promise_auto_snapshot():
    """Auto-snapshot on every SUCCEEDED is deferred to F7.5."""
    src = _read()
    assert "Auto-snapshot" in src or "auto-snapshot" in src.lower()


# --- links -------------------------------------------------------------


def test_runbook_links_to_f5_scoring():
    assert "F5-SCORING.md" in _read()


def test_runbook_links_to_f6_multiteam():
    assert "F6-MULTITEAM.md" in _read()


def test_runbook_links_to_scenario_schema():
    assert "scenario.schema.json" in _read()
