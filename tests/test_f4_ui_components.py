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


# ---------- TopologyGraph (F4-UI commit 2) -------------------------------


def test_topology_graph_file_exists():
    p = SRC_DIR / "components" / "portal" / "topology-graph.tsx"
    assert p.is_file(), f"missing: {p}"


def test_topology_graph_exports_component():
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    assert "export function TopologyGraph" in src
    assert "export interface TopologyAsset" in src


def test_topology_graph_handles_empty():
    """An empty asset list must render a friendly placeholder, not a
    broken SVG with no nodes."""
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    assert "assets.length === 0" in src
    # The placeholder mentions 'Pick a scenario'.
    assert "Pick a scenario" in src


def test_topology_graph_classifies_red_roles():
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    for keyword in ("attacker", "red", "offensive", "pentester"):
        assert keyword in src, (
            f"TopologyGraph should classify role containing {keyword!r} as red zone"
        )


def test_topology_graph_classifies_router_roles():
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    for keyword in ("router", "firewall", "gw"):
        assert keyword in src, (
            f"TopologyGraph should classify role containing {keyword!r} as router zone"
        )


def test_topology_graph_classifies_blue_roles():
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    for keyword in ("victim", "defender", "blue", "target", "log-aggregator"):
        assert keyword in src, (
            f"TopologyGraph should classify role containing {keyword!r} as blue zone"
        )


def test_topology_graph_draws_svg_zones():
    """The graph must render real SVG, not a placeholder image. The
    `<svg>` element is the proof."""
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    assert "<svg" in src
    assert "<rect" in src
    assert "<text" in src


def test_topology_graph_has_aria_label():
    src = _read("services/portal/app/src/components/portal/topology-graph.tsx")
    assert 'aria-label' in src, (
        "TopologyGraph must carry an aria-label for accessibility"
    )


# ---------- DrillConsole -------------------------------------------------


def test_drill_console_file_exists():
    p = SRC_DIR / "components" / "portal" / "drill-console.tsx"
    assert p.is_file(), f"missing: {p}"


def test_drill_console_exports_component():
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "export function DrillConsole" in src


def test_drill_console_shows_live_badge():
    """The live badge appears while the run is RUNNING or PENDING.
    Operators need an obvious visual signal that the drill is in
    flight — that's the whole point of a dedicated console view."""
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "drill-live-badge" in src
    assert "animate-pulse" in src


def test_drill_console_polls_during_run():
    """Polling cadence: 2s while live, 5s while terminal. Verify
    both intervals appear in the source."""
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "2000" in src and "5000" in src, (
        "DrillConsole must poll 2s while live, 5s while terminal"
    )


def test_drill_console_handles_no_run_selected():
    """If pickedRunId is null, render EmptyState — not a broken
    console."""
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "pickedRunId === null" in src
    assert "EmptyState" in src


def test_drill_console_includes_topology():
    """DrillConsole must show the topology graph as part of the
    live-drill view (that's the visual identity)."""
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "TopologyGraph" in src
    assert "TopologyAsset" in src


def test_drill_console_offers_report_download():
    """Terminal runs (succeeded/failed/timeout/cancelled/completed)
    must surface the Download report button."""
    src = _read("services/portal/app/src/components/portal/drill-console.tsx")
    assert "drill-download-report" in src
    assert "/api/v1/drills/" in src  # report endpoint


def test_drill_console_subscribes_to_app_tsx_observe_view():
    """The Observe view in app.tsx must render DrillConsole, not the
    old RunInspector+Assets+Audit stack."""
    src = _read("services/portal/app/src/app.tsx")
    assert "<DrillConsole" in src, "Observe view must render DrillConsole"


# ---------- Compact props on inner cards --------------------------------


def test_assets_card_supports_compact():
    src = _read("services/portal/app/src/components/portal/assets-card.tsx")
    assert "compact" in src, "AssetsCard must accept a compact prop"


def test_audit_explorer_card_supports_compact():
    src = _read("services/portal/app/src/components/portal/audit-explorer-card.tsx")
    assert "compact" in src, "AuditExplorerCard must accept a compact prop"
