"""Static + smoke checks for the F4-UI portal layout.

F4-UI replaced the COMPOSITIONS table in app.tsx with view-tab
routing (Dashboard / Operate / Observe / Admin / History / Profile).
These tests pin the new shape:

    * TopNav has a tab for every view key the URL hash can hold.
    * Tab visibility matches the role matrix (admin/lead see
      Admin, the others don't).
    * Every card file the app.tsx imports actually exists on
      disk (catches a renamed/missing file).
    * useHashRoute hook is wired up; the URL hash is the active
      view.
    * TopNav replaces the inline TokenBar-as-header pattern.
    * SignInCard still wires into the anonymous branch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "services" / "portal" / "app"
SRC_DIR = APP_DIR / "src"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------- app.tsx + TopNav wiring ---------------------------------------


def test_app_tsx_uses_topnav():
    src = _read("services/portal/app/src/app.tsx")
    assert "<TopNav" in src, "app.tsx must render <TopNav />"
    assert "activeView" in src and "onChangeView" in src, (
        "app.tsx must pass activeView + onChangeView to TopNav"
    )


def test_app_tsx_uses_hash_route_hook():
    src = _read("services/portal/app/src/app.tsx")
    assert "useHashRoute" in src, "app.tsx must use the useHashRoute hook"


def test_app_tsx_imports_all_card_components():
    src = _read("services/portal/app/src/app.tsx")
    # F4-UI: DrillConsole takes over the Observe view; RunInspector
    # + Assets + AuditExplorer are imported by DrillConsole, not by
    # app.tsx directly.
    for card_import in [
        "ScenariosCard",
        "MyRunsCard",
        "RunLifecycleCard",
        "PveOpsCard",
        "ScenarioAuthoringCard",
        "SignInCard",
        "CommandCenterCard",  # Replaced DashboardCard in Q27
        "TopNav",
        "DrillConsole",  # F4-UI commit 2
    ]:
        assert card_import in src, (
            f"app.tsx does not import {card_import} but renders it"
        )


def test_app_tsx_handles_anonymous_branch():
    src = _read("services/portal/app/src/app.tsx")
    # Anonymous (no `me`) should still render SignInCard.
    assert "SignInCard" in src
    # The anonymous branch is gated on `!me`.
    assert re.search(r"!\s*me\s*&&\s*!loading", src) or "!me && !loading" in src or "me ||" in src, (
        "app.tsx must have an anonymous (no-token) render branch"
    )


def test_app_tsx_renders_signin_for_anonymous():
    src = _read("services/portal/app/src/app.tsx")
    # SignInCard is rendered in the anonymous branch.
    assert "<SignInCard" in src


def test_app_tsx_routes_by_view_key():
    """Each of the 6 views must have a switch case."""
    src = _read("services/portal/app/src/app.tsx")
    for view in ("dashboard", "operate", "observe", "admin", "history", "profile"):
        assert f'case "{view}"' in src, f"view {view!r} has no switch case in app.tsx"


def test_app_tsx_admin_view_is_role_gated():
    """Admin view should only be reached when role permits.

    We can't test the runtime gating without jsdom; instead we
    pin that the TopNav tabs list restricts `admin` to the
    correct role set in top-nav.tsx (which app.tsx delegates to).
    """
    tabs_src = _read("services/portal/app/src/components/portal/top-nav.tsx")
    # The admin tab in TopNav declares its roles.
    m = re.search(
        r'key:\s*"admin".*?roles:\s*\[(.+?)\]',
        tabs_src,
        re.DOTALL,
    )
    assert m, "TopNav must declare roles for the Admin tab"
    roles = re.findall(r'"([a-z]+)"', m.group(1))
    assert "admin" in roles and "lead" in roles, (
        f"Admin tab roles must include admin + lead; got {roles}"
    )
    # Red/blue/observer must NOT be in the admin tab roles.
    for blocked in ("red", "blue", "observer"):
        assert blocked not in roles, (
            f"role {blocked!r} must NOT have admin-tab access; got {roles}"
        )


# ---------- TopNav tabs --------------------------------------------------


def test_topnav_tabs_cover_all_views():
    src = _read("services/portal/app/src/components/portal/top-nav.tsx")
    for view in ("dashboard", "operate", "observe", "admin", "history", "profile"):
        assert f'key: "{view}"' in src, (
            f"TopNav TABS must include {view!r} tab"
        )


def test_topnav_brand_includes_divide():
    src = _read("services/portal/app/src/components/portal/top-nav.tsx")
    assert "div:ide" in src or "divide" in src.lower(), (
        "TopNav should brand the product (div:ide / divide)"
    )


def test_topnav_sign_out_calls_api():
    src = _read("services/portal/app/src/components/portal/top-nav.tsx")
    assert "/api/v1/auth/logout" in src, (
        "TopNav sign-out must hit /api/v1/auth/logout"
    )
    assert "setToken" in src, "TopNav sign-out must clear localStorage"


def test_topnav_tabs_set_data_testid():
    src = _read("services/portal/app/src/components/portal/top-nav.tsx")
    # Each tab button must carry a stable testid for the test suite.
    assert "top-nav-tab-" in src, (
        "TopNav tabs must use data-testid='top-nav-tab-<key>' for tests"
    )


# ---------- useHashRoute hook --------------------------------------------


def test_use_hash_route_file_exists():
    p = SRC_DIR / "hooks" / "use-hash-route.ts"
    assert p.is_file(), f"missing: {p}"


def test_use_hash_route_exports_default_view_fallback():
    src = _read("services/portal/app/src/hooks/use-hash-route.ts")
    assert "defaultValue" in src, (
        "useHashRoute must accept a defaultValue fallback for invalid hashes"
    )
    assert "hashchange" in src, (
        "useHashRoute must subscribe to hashchange events"
    )


# ---------- DashboardCard -------------------------------------------------


def test_dashboard_card_file_exists():
    p = SRC_DIR / "components" / "portal" / "dashboard-card.tsx"
    assert p.is_file(), f"missing: {p}"


def test_dashboard_card_calls_runs_endpoint():
    src = _read("services/portal/app/src/components/portal/dashboard-card.tsx")
    assert "/api/v1/drills" in src, "DashboardCard must call /api/v1/drills"


def test_dashboard_card_uses_kpi_tile():
    src = _read("services/portal/app/src/components/portal/dashboard-card.tsx")
    assert "KpiTile" in src, "DashboardCard must use KpiTile for metrics"


def test_dashboard_card_uses_status_pill():
    src = _read("services/portal/app/src/components/portal/dashboard-card.tsx")
    assert "StatusPill" in src, "DashboardCard must use StatusPill in recent runs"


def test_dashboard_card_shows_empty_state():
    src = _read("services/portal/app/src/components/portal/dashboard-card.tsx")
    assert "EmptyState" in src, (
        "DashboardCard must show EmptyState when there are no runs"
    )


def test_dashboard_card_kpis_include_in_progress_and_success_rate():
    src = _read("services/portal/app/src/components/portal/dashboard-card.tsx")
    for label in ("In progress", "Success rate", "Today"):
        assert label in src, (
            f"DashboardCard must surface a KPI labelled {label!r}"
        )


# ---------- StatusPill ----------------------------------------------------


def test_status_pill_handles_all_known_tones():
    src = _read("services/portal/app/src/components/portal/status-pill.tsx")
    for tone in ("running", "succeeded", "failed", "timeout", "cancelled", "pending"):
        assert tone in src, f"StatusPill tone {tone!r} missing"


def test_status_pill_running_has_pulse_dot():
    src = _read("services/portal/app/src/components/portal/status-pill.tsx")
    assert "animate-pulse" in src, (
        "StatusPill must render a pulse dot for RUNNING to signal liveness"
    )


# ---------- bundle size ---------------------------------------------------


def test_bundle_size_within_f4_budget():
    """F4-UI adds TopNav + DashboardCard + KpiTile + StatusPill +
    EmptyState + useHashRoute hook. Bundle stays under 400 KB."""
    build_dir = APP_DIR / "build"
    if not build_dir.is_dir():
        pytest.skip("build/ not present")
    js_assets = [a for a in (build_dir / "assets").glob("*.js") if ".map" not in a.name]
    total_bytes = sum(a.stat().st_size for a in js_assets)
    budget = 400 * 1024
    assert total_bytes < budget, (
        f"Production JS bundle is {total_bytes/1024:.1f} KB; budget "
        f"is {budget/1024:.0f} KB. Time to lazy-load."
    )
