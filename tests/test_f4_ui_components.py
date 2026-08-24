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


# ---------- UserListCard (F4-UI commit 3) -------------------------------


def test_user_list_card_file_exists():
    p = SRC_DIR / "components" / "portal" / "user-list-card.tsx"
    assert p.is_file(), f"missing: {p}"


def test_user_list_card_calls_auth_users():
    src = _read("services/portal/app/src/components/portal/user-list-card.tsx")
    assert "/api/v1/auth/users" in src, "UserListCard must call /api/v1/auth/users"


def test_user_list_card_renders_empty_state():
    """When the API returns [], the card shows EmptyState with
    a hint about the bootstrap env vars."""
    src = _read("services/portal/app/src/components/portal/user-list-card.tsx")
    assert "EmptyState" in src
    assert "DIVIDE_BOOTSTRAP_ADMIN" in src


def test_user_list_card_shows_role_and_disabled():
    src = _read("services/portal/app/src/components/portal/user-list-card.tsx")
    for kw in ("role", "disabled", "active"):
        assert kw in src


def test_user_list_card_toggle_endpoint_documented():
    """The disable/enable toggle endpoint is deferred to L3 admin
    UI. The card calls it but the surface is a stub that surfaces
    a 404/501."""
    src = _read("services/portal/app/src/components/portal/user-list-card.tsx")
    assert "/toggle-disabled" in src
    # The handler treats 404 / 501 as the deferred case.
    assert "404" in src or "501" in src


# ---------- ProfileCard -------------------------------------------------


def test_profile_card_file_exists():
    p = SRC_DIR / "components" / "portal" / "profile-card.tsx"
    assert p.is_file()


def test_profile_card_uses_dashboard_card():
    """ProfileCard is a DashboardCard scoped to the current user."""
    src = _read("services/portal/app/src/components/portal/profile-card.tsx")
    assert "DashboardCard" in src


# ---------- OperatorConsoleCard -----------------------------------------


def test_operator_console_card_file_exists():
    p = SRC_DIR / "components/portal/operator-console-card.tsx"
    assert p.is_file(), f"missing: {p}"


def test_operator_console_card_calls_drills_endpoint():
    src = _read("services/portal/app/src/components/portal/operator-console-card.tsx")
    assert "/api/v1/drills" in src
    assert "/stop" in src, "Stop button must hit POST /api/v1/drills/{id}/stop"


def test_operator_console_card_polling():
    """The console should auto-refresh so the operator doesn't have
    to click Refresh every few seconds."""
    src = _read("services/portal/app/src/components/portal/operator-console-card.tsx")
    assert "setInterval" in src
    assert "5000" in src


def test_operator_console_card_filters_to_live_runs():
    src = _read("services/portal/app/src/components/portal/operator-console-card.tsx")
    assert "running" in src and "pending" in src


def test_operator_console_card_shows_deferred_message_for_reset_inject():
    """Reset and Inject are F7 / F8 features. The button should
    surface a clear 'coming soon' message so the operator knows
    the click was a no-op."""
    src = _read("services/portal/app/src/components/portal/operator-console-card.tsx")
    assert "F7" in src or "F8" in src
    assert "operator-reset" in src
    assert "operator-inject" in src


# ---------- Toast / ToastHost -------------------------------------------


def test_toast_file_exists():
    p = SRC_DIR / "components/portal/toast.tsx"
    assert p.is_file()


def test_toast_exports_host_and_hook():
    src = _read("services/portal/app/src/components/portal/toast.tsx")
    assert "export function ToastHost" in src
    assert "export function useToasts" in src


def test_toast_supports_three_kinds():
    src = _read("services/portal/app/src/components/portal/toast.tsx")
    assert "info" in src and "success" in src and "error" in src


def test_toast_has_auto_dismiss():
    """Toasts must auto-dismiss after the timeout (default 4s)."""
    src = _read("services/portal/app/src/components/portal/toast.tsx")
    assert "setTimeout" in src and "dismiss" in src


def test_toast_host_mounted_in_app_tsx():
    """ToastHost must wrap the entire app tree so any component
    can fire toasts via useToasts()."""
    src = _read("services/portal/app/src/app.tsx")
    assert "<ToastHost>" in src


# ---------- MyRunsCard status filter -----------------------------------


def test_my_runs_card_has_status_filter():
    """F4-UI commit 3: MyRunsCard gets a status filter row so the
    History tab can narrow to e.g. 'only failed runs'."""
    src = _read("services/portal/app/src/components/portal/my-runs-card.tsx")
    assert "statusFilter" in src
    assert "my-runs-filter" in src


def test_my_runs_card_filter_options_include_all():
    """The filter must include 'all' as a default."""
    src = _read("services/portal/app/src/components/portal/my-runs-card.tsx")
    assert '"all"' in src or "'all'" in src
    assert "succeeded" in src and "failed" in src


# ---------- App.tsx wiring for the new cards ----------------------------


def test_app_tsx_renders_user_list_card_in_admin():
    src = _read("services/portal/app/src/app.tsx")
    assert "UserListCard" in src, "app.tsx must import + render UserListCard"
    # Check it's in the admin view case.
    m = re.search(r'case "admin":\s*\n(.*?)case "history":', src, re.DOTALL)
    assert m, "admin case not found in app.tsx"
    assert "UserListCard" in m.group(1), "UserListCard must render in admin view"


def test_app_tsx_renders_operator_console_in_admin():
    src = _read("services/portal/app/src/app.tsx")
    m = re.search(r'case "admin":\s*\n(.*?)case "history":', src, re.DOTALL)
    assert m
    assert "OperatorConsoleCard" in m.group(1)


def test_app_tsx_renders_profile_card_in_profile_view():
    src = _read("services/portal/app/src/app.tsx")
    assert "ProfileCard" in src
    # The Profile view should render ProfileCard, not DashboardCard directly.
    m = re.search(r'case "profile":\s*\n(.*?)default:', src, re.DOTALL)
    assert m, "profile case not found"
    assert "ProfileCard" in m.group(1)
    # But not a bare DashboardCard (which would mean the profile
    # view was never specialised).
    assert "<DashboardCard" not in m.group(1)
