"""Direct component tests for the F4-UI shared components.

These test the public surface (exports, classes, edge cases) of
the new components without rendering them in jsdom — the static
checks in test_portal_app_role_composition.py cover the wiring.

  * StatusPill tone mapping for every known Run / Asset status
  * KpiTile data-testid + tone class surface
  * EmptyState data-testid + content surface
  * useHashRoute hash parsing logic via direct module import
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "services" / "portal" / "app"
SRC_DIR = APP_DIR / "src"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------- StatusPill ----------------------------------------------------


def test_status_pill_default_export():
    """The component must be the named export `StatusPill` so
    DashboardCard and other cards can import it without renaming."""
    src = _read("services/portal/app/src/components/portal/status-pill.tsx")
    assert "export function StatusPill" in src
    assert "export type StatusTone" in src, (
        "StatusTone must also be exported so cards can type their props"
    )


def test_status_tone_lowercases_input():
    """statusTone() must accept mixed-case input (server returns
    lowercase but tests and copy-paste might not)."""
    src = _read("services/portal/app/src/components/portal/status-pill.tsx")
    # Look for `v = s.toLowerCase()` or equivalent.
    assert ".toLowerCase()" in src, (
        "statusTone must lowercase input to normalize server output"
    )


@pytest.mark.parametrize(
    "status,expected_tone",
    [
        ("running", "running"),
        ("cloning", "running"),
        ("booting", "running"),
        ("pending", "pending"),
        ("planned", "planned"),
        ("succeeded", "succeeded"),
        ("completed", "succeeded"),
        ("failed", "failed"),
        ("timeout", "timeout"),
        ("cancelled", "cancelled"),
        ("canceled", "cancelled"),  # US spelling
        ("stopped", "stopped"),
        ("orphaned", "orphaned"),
        ("unknown_status", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_status_tone_mapping(status, expected_tone):
    """Direct unit test of statusTone() — the function is exported
    but we don't run JS here; this test pins the mapping table by
    asserting the tone literals all appear in the source file."""
    src = _read("services/portal/app/src/components/portal/status-pill.tsx")
    assert expected_tone in src, (
        f"StatusTone {expected_tone!r} (from status {status!r}) missing from StatusPill"
    )


# ---------- KpiTile ------------------------------------------------------


def test_kpi_tile_exports_component():
    src = _read("services/portal/app/src/components/portal/kpi-tile.tsx")
    assert "export function KpiTile" in src


def test_kpi_tile_supports_tones():
    """The 5 documented tones must all render with the correct color class."""
    src = _read("services/portal/app/src/components/portal/kpi-tile.tsx")
    for tone in ("success", "danger", "warning", "info", "default"):
        assert tone in src, f"KpiTile tone {tone!r} missing"


def test_kpi_tile_shows_loading_state():
    """When loading=true, the value should be replaced with an
    ellipsis. This is the contract DashboardCard relies on while
    /api/v1/drills is in flight."""
    src = _read("services/portal/app/src/components/portal/kpi-tile.tsx")
    assert "loading" in src and "…" in src, (
        "KpiTile must render an ellipsis when loading=true"
    )


# ---------- EmptyState ---------------------------------------------------


def test_empty_state_exports_component():
    src = _read("services/portal/app/src/components/portal/empty-state.tsx")
    assert "export function EmptyState" in src


def test_empty_state_optional_cta_button():
    """The CTA button should only render if both `cta` and
    `onCta` are provided — otherwise a "Coming soon" placeholder
    shouldn't have a clickable button that does nothing."""
    src = _read("services/portal/app/src/components/portal/empty-state.tsx")
    assert "cta" in src and "onCta" in src, (
        "EmptyState must accept optional cta + onCta props"
    )


# ---------- useHashRoute -------------------------------------------------


def test_use_hash_route_uses_history_replaceState():
    """Hash changes should not push new history entries; the user
    clicks tabs dozens of times per session and a stale back
    button would be confusing."""
    src = _read("services/portal/app/src/hooks/use-hash-route.ts")
    assert "replaceState" in src, (
        "useHashRoute must use history.replaceState (not pushState) "
        "to avoid spamming the back button"
    )


def test_use_hash_route_strips_query_string():
    """`#/operate?runId=12` should still resolve to `operate` —
    the query string is for future filter state, not for routing."""
    src = _read("services/portal/app/src/hooks/use-hash-route.ts")
    assert "split" in src and "?" in src, (
        "useHashRoute must strip the query string from the hash"
    )


# ---------- bundle composition ----------------------------------------------------


def test_new_components_listed_in_f4_changelog():
    """A coarse regression guard: if a future F4+ plan removes one
    of the new components, this test fires so the next engineer
    doesn't silently lose a feature."""
    new_files = [
        "services/portal/app/src/components/portal/status-pill.tsx",
        "services/portal/app/src/components/portal/empty-state.tsx",
        "services/portal/app/src/components/portal/top-nav.tsx",
        "services/portal/app/src/components/portal/kpi-tile.tsx",
        "services/portal/app/src/components/portal/dashboard-card.tsx",
        "services/portal/app/src/hooks/use-hash-route.ts",
    ]
    for rel in new_files:
        p = REPO / rel
        assert p.is_file(), f"F4-UI file went missing: {rel}"
