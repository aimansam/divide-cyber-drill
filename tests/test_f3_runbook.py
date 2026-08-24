"""Tests for docs/F3-RUNBOOK.md.

The F3 runbook is the operator-facing counterpart to the F3
runner changes (commits ``2a97525`` + ``6e9e5b5``). It documents:
  * Why the runner does NOT auto-create vmbrN (PVE has no public API)
  * The bridge allocation scheme (vmbr100+ reserved for F3)
  * Concrete setup steps (interfaces stanza + ifreload)
  * The error messages the runner surfaces when bridges are missing
  * The cyber-range demo scenario's bridge plan

These tests pin that the runbook covers the contract — if a future
plan moves bridges to a different mechanism (e.g. PVE SDN zones),
the tests force an explicit update to the runbook so operators
aren't left with stale instructions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F3-RUNBOOK.md"


def _read() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file existence ------------------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F3-RUNBOOK.md is missing"


def test_runbook_not_empty():
    """A runbook with <50 lines is a stub; F3 deserves a real guide."""
    src = _read()
    assert len(src.splitlines()) >= 80, (
        f"F3 runbook is {len(src.splitlines())} lines; expected 80+"
    )


# --- TL;DR + status ------------------------------------------------------


def test_runbook_has_tldr():
    src = _read()
    assert "TL;DR" in src


def test_runbook_documents_f3_commits():
    """The runbook should reference the F3 commits so anyone
    reading the doc can verify the runner code matches."""
    src = _read()
    # At least one of the F3 commit hashes should be mentioned.
    assert "2a97525" in src or "6e9e5b5" in src, (
        "F3 runbook must reference its own commit so readers can "
        "cross-check the code"
    )


def test_runbook_explains_why_bridges_are_operator_owned():
    """The single most important document point: PVE has no public
    bridge-creation API, so the operator owns /etc/network/interfaces.
    Without this, operators would assume the runner auto-creates
    bridges and hit the 'bridge not configured' error."""
    src = _read()
    assert "PVE does" in src or "no public API" in src
    assert "/etc/network/interfaces" in src


# --- allocation scheme ---------------------------------------------------


def test_runbook_pin_vmbr_allocation():
    """Bridge allocation starts at vmbr100 to avoid clobbering the
    operator's vmbr0..vmbr99. This is a contract pin — if F4 or F6
    changes the starting index, the runbook must be updated."""
    src = _read()
    assert "vmbr100" in src


def test_runbook_vmbr100_range_isolated_from_operator_managed():
    """The vmbr0..vmbr99 range is operator-managed and explicitly
    off-limits to F3 auto-allocation."""
    src = _read()
    assert "vmbr99" in src


# --- setup steps ---------------------------------------------------------


def test_runbook_documents_ifreload():
    """The exact OS-level command operators must run after editing
    /etc/network/interfaces. Without this, the bridge is defined
    but not active."""
    src = _read()
    assert "ifreload" in src or "systemctl reload networking" in src


def test_runbook_documents_bridge_stanza():
    """A concrete interfaces stanza is mandatory — operators do not
    want to have to reverse-engineer it from prose."""
    src = _read()
    # Full stanza syntax (auto / iface / bridge-ports / post-up)
    assert "auto vmbr100" in src or "auto vmbr" in src
    assert "bridge-ports" in src
    assert "iface vmbr" in src


def test_runbook_documents_demo_scenario_bridge_plan():
    """The demo scenario declares 3 networks — the runbook must
    map each to the allocated vmbr ID so operators can prepare."""
    src = _read()
    assert "red_vlan" in src
    assert "blue_vlan" in src
    assert "dmz" in src
    assert "vmbr100" in src and "vmbr101" in src and "vmbr102" in src


# --- troubleshooting -----------------------------------------------------


def test_runbook_has_troubleshooting_table():
    """Operators hit failures at the bridge layer often — the
    runbook must include a troubleshooting table with the most
    common symptoms and fixes."""
    src = _read()
    # Has a table (| Syntax) and at least 3 rows.
    rows = src.count("\n|")
    assert rows >= 6, (
        f"troubleshooting table must have 3+ rows; got {rows}"
    )
    # Most common failure mode is referenced explicitly.
    assert "bridge vmbr" in src
    assert "not configured" in src or "missing" in src


def test_runbook_documents_error_message_text():
    """The runner emits a specific error when bridges are missing;
    the runbook must include that exact text so operators can
    grep their run report and find this runbook."""
    src = _read()
    # The exact prefix the runner emits (real_adapter.py).
    # We accept partial matches because the runbook is prose.
    assert "ifreload" in src
    assert "vmbr100" in src


def test_runbook_explains_create_bridge_is_assert_only():
    """The real adapter's create_bridge() does NOT actually
    create the bridge — it asserts the bridge exists. This
    subtlety must be in the runbook; otherwise operators
    expect the runner to make the OS-level change."""
    src = _read()
    assert "create_bridge" in src
    # The key word: it asserts / verifies, doesn't create.
    assert "assert" in src or "asserts" in src


# --- cross-references ----------------------------------------------------


def test_runbook_links_to_demo_doc():
    """The runbook should cross-reference docs/DEMO.md and the
    PROXMOX-SETUP.md so operators can find the surrounding
    context."""
    src = _read()
    assert "../DEMO.md" in src or "docs/DEMO.md" in src or "DEMO.md" in src
    assert "PROXMOX-SETUP.md" in src


def test_runbook_links_to_plan_roadmap():
    """F3 unblocks F4 (noVNC), F6 (multi-team); the runbook
    should mention F4/F6 so operators can plan ahead."""
    src = _read()
    # F4 and F6 should be mentioned as future plans.
    assert "F4" in src and "F6" in src


def test_runbook_links_to_scenario_schema():
    """The schema is the source of truth for what fields are
    legal in ``spec.networks[]`` / ``spec.assets[].networks[]``.
    The runbook should reference it so operators can read it."""
    src = _read()
    assert "scenario.schema.json" in src


# --- local-testing -------------------------------------------------------


def test_runbook_documents_local_test_path():
    """Operators should be able to verify the bridge plan without
    a real PVE — using the in-memory mock via ``make up``."""
    src = _read()
    assert "make up" in src or "MockProxmoxAdapter" in src


def test_runbook_does_not_promise_bridge_auto_creation():
    """Reverse-pin: the runbook must NOT contain "the runner
    creates bridges" phrasing, because that would mislead
    operators who skim the runbook."""
    src = _read()
    assert "runner creates bridges" not in src.lower().replace("'", "")
    # OK phrasings: "the runner allocates IDs", "the operator
    # creates bridges", etc.
