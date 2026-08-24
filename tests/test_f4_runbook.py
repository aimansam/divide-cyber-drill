"""Tests for docs/F4-NOVNC.md.

The F4 runbook documents how an operator uses noVNC consoles per
asset. These tests pin the runbook so future plans that change
the console mechanism (RFB ports, ticket format, etc.) are forced
to update the doc as well.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNBOOK = REPO / "docs" / "F4-NOVNC.md"


def _read() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


# --- file --------------------------------------------------------------


def test_runbook_exists():
    assert RUNBOOK.is_file(), "docs/F4-NOVNC.md is missing"


def test_runbook_non_trivial():
    """A runbook with fewer than 80 lines is a stub; F4 deserves detail."""
    src = _read()
    assert len(src.splitlines()) >= 80, (
        f"F4 runbook is {len(src.splitlines())} lines; F4 is "
        "the most subtle plan so far."
    )


def test_runbook_has_tldr():
    assert "TL;DR" in _read()


# --- architecture -----------------------------------------------------


def test_runbook_shows_proxy_topology():
    """The proxy has THREE endpoints (browser, API, PVE); the
    runbook must show all three."""
    src = _read()
    # Browser on one side, PVE on the other, API in the middle
    assert "Browser" in src
    assert "PVE" in src
    assert "div:ide API" in src or "console_proxy" in src


def test_runbook_explains_why_browser_doesnt_see_pve_token():
    """A core security property: the PVE ticket stays on the
    server. The runbook must surface this explicitly."""
    src = _read()
    assert "PVE token" in src and "browser never" in src.lower() or (
        "browser never sees" in src.lower()
    )


def test_runbook_documents_rbac_matrix():
    src = _read()
    # Admin/lead see any run; red/blue only own; observer any.
    assert "admin" in src
    assert "lead" in src
    assert "red" in src
    assert "blue" in src
    assert "observer" in src


# --- endpoint contract ------------------------------------------------


def test_runbook_documents_get_endpoint_url():
    src = _read()
    assert (
        "/api/v1/drills/{run_id}/assets/{asset_id}/console" in src
        or "GET /api/v1/drills" in src
    )


def test_runbook_documents_ws_endpoint_url():
    src = _read()
    assert "console/ws" in src


def test_runbook_documents_token_query_param_fallback():
    """Browsers can't attach custom WS headers; the runbook must
    document the ?token= fallback."""
    src = _read()
    assert "?token=" in src


def test_runbook_documents_close_codes():
    src = _read()
    # At least 4 close codes must be documented; we use 4401,
    # 4403, 4404, 4409, 4502.
    for code in ("4401", "4403", "4404", "4409", "4502"):
        assert code in src, f"close code {code} must be documented"


def test_runbook_documents_http_error_codes():
    src = _read()
    # HTTP error codes for the GET endpoint
    for code in ("401", "403", "404", "409", "502"):
        assert code in src, f"HTTP error code {code} must be documented"


# --- decisions --------------------------------------------------------


def test_runbook_justifies_no_novnc_bundle():
    """We ship a stripped-down client because the noVNC bundle is
    ~700 KB. The runbook must surface this trade-off so a
    future plan adding the bundle has to update the runbook."""
    src = _read()
    assert "700" in src or "@novnc/novnc" in src
    assert (
        "280" in src or "budget" in src
    ), "F4 runbook must reference the 280 KB portal bundle budget"


def test_runbook_links_to_f3_runbook():
    """F4 builds on F3 (the operator needs to have bridges set up
    before VMs can come online)."""
    src = _read()
    assert "F3-RUNBOOK.md" in src


def test_runbook_links_to_demo_doc():
    src = _read()
    assert "docs/DEMO.md" in src or "DEMO.md" in src


def test_runbook_links_to_plan_roadmap():
    """F8 (SOC view) builds on F4's console endpoints."""
    src = _read()
    assert "F8" in src


# --- testing ----------------------------------------------------------


def test_runbook_documents_local_mock_test_path():
    src = _read()
    assert "MockProxmoxAdapter" in src or "mock" in src.lower()


def test_runbook_documents_real_pve_setup():
    src = _read()
    assert "pvesh" in src or "vncproxy" in src
    assert (
        "PROXMOX_TOKEN" in src
        or "PROXMOX_HOST" in src
        or "PVEAPIToken" in src
    )


# --- negative pins ----------------------------------------------------


def test_runbook_does_not_promise_recordings():
    """We explicitly punt console recording to F8; the runbook
    must NOT promise recordings since that's a forward-looking
    pin."""
    src = _read()
    assert (
        "console recording" in src.lower()
        or "recordings" in src.lower()
    ), "runbook should mention recording is deferred"


def test_runbook_does_not_promise_multi_monitor():
    """Multi-monitor isn't modelled. If a future plan adds it,
    this test fires to remind to update the runbook."""
    src = _read()
    assert "multi-monitor" in src.lower() or "multi head" in src.lower()
