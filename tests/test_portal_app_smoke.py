"""Smoke + invariants for the React/Vite user portal at /portal/app/.

Day-1 deliverables (M1 + M3.1 in the next-plan):

  * Vite-built bundle served by FastAPI StaticFiles mount
  * TokenBar component (sign-in form, X-Divide-Token on every fetch)
  * ScenariosCard (M3.1)

This test asserts the bundle exists on disk, its mount resolves on a
live API, and the source tree references the components it should.

Run with the API up (the FastAPI fixture starts one in-process) and
a Vite build present at services/portal/app/build/. The build step
runs via `npm run build` in that dir; CI does this before invoking
pytest (Makefile target ``make portal-build``).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "services" / "portal" / "app"
BUILD_DIR = APP_DIR / "build"
SRC_DIR = APP_DIR / "src"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------- build artifact presence ---------------------------------------


def test_build_directory_exists_after_npm_run_build():
    """`npm run build` produces services/portal/app/build/ with index.html
    + assets/. The build step is part of the deploy pipeline; if you ran
    pytest without first running the build, this test will tell you.
    """
    if not BUILD_DIR.is_dir():
        pytest.skip(
            "services/portal/app/build/ not found — run `npm run build` "
            "in services/portal/app/ first"
        )
    assert (BUILD_DIR / "index.html").exists()
    assert (BUILD_DIR / "assets").is_dir()
    # Vite emits hashed asset names; we don't pin the hash but we do
    # assert at least one JS + one CSS asset.
    assets = list((BUILD_DIR / "assets").iterdir())
    js = [a for a in assets if a.suffix == ".js" and ".map" not in a.name]
    css = [a for a in assets if a.suffix == ".css"]
    assert js, f"no JS bundle in {BUILD_DIR / 'assets'}"
    assert css, f"no CSS bundle in {BUILD_DIR / 'assets'}"


def test_built_index_html_references_correct_base_path():
    """The built index.html must reference assets under /portal/app/
    (not the Vite dev server's root-relative paths). A regression here
    would mean the bundle 404s when served behind /portal/app/.
    """
    if not BUILD_DIR.is_dir():
        pytest.skip("build/ not present")
    html = _read("services/portal/app/build/index.html")
    assert "/portal/app/assets/" in html, (
        "Built index.html must reference /portal/app/assets/...; "
        "vite.config.ts `base` field is wrong"
    )
    for ref in re.findall(r"/portal/app/assets/([\w\.\-]+)", html):
        assert (BUILD_DIR / "assets" / ref).exists(), (
            f"Bundle references /portal/app/assets/{ref} but that file "
            f"isn't in build/assets/"
        )


# ---------- source invariants ---------------------------------------------


def test_app_source_references_x_divide_token_header():
    """The portal must send X-Divide-Token on every fetch. The literal
    string lives in src/lib/api.ts; if someone renames the header
    without updating the API middleware, this test fails.
    """
    api_ts = (SRC_DIR / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "X-Divide-Token" in api_ts


def test_app_source_references_scenarios_endpoint():
    """scenarios-card.tsx fetches /api/v1/scenarios on mount. Drop the
    fetch and the page silently renders an empty list.
    """
    src = (SRC_DIR / "components" / "portal" / "scenarios-card.tsx").read_text(
        encoding="utf-8"
    )
    assert '"/api/v1/scenarios"' in src


def test_app_source_uses_shadcn_ui_card():
    """We picked Card from shadcn/ui on day 1. If someone replaces it
    with a hand-rolled <div>, this test flags the divergence so we
    notice.
    """
    src = (SRC_DIR / "components" / "portal" / "scenarios-card.tsx").read_text(
        encoding="utf-8"
    )
    assert 'from "@/components/ui/card"' in src


def test_app_entry_script_marker_is_present():
    """index.html at the portal root must reference /src/main.tsx so
    Vite's dev server (and the build step) pick up main.tsx as the
    entry. A regression here means the bundle never mounts.
    """
    html = (APP_DIR / "index.html").read_text(encoding="utf-8")
    assert "/src/main.tsx" in html


# ---------- live mount (when build/ exists) -------------------------------


def test_portal_app_serves_index_html_via_staticfiles(client: TestClient):
    """Hit /portal/app/ and assert the response is the built HTML
    (not the source-tree HTML and not a 404).
    """
    if not BUILD_DIR.is_dir():
        pytest.skip("build/ not present; bundle not testable")
    r = client.get("/portal/app/")
    assert r.status_code == 200, f"GET /portal/app/ -> {r.status_code}"
    body = r.text
    assert "<div id=\"root\"" in body, (
        "Response is not the React app — got the source-tree HTML or a "
        "different mount's index.html"
    )
    assert "/portal/app/assets/" in body, (
        "Built bundle path is missing — vite.config.ts base field is "
        "wrong, or main.py mounted the source dir instead of build/"
    )


def test_portal_app_serves_assets(client: TestClient):
    """The asset referenced in the built index.html must also resolve.
    Catches a mount-order bug where the parent /portal mount shadows
    the /portal/app/ submount.
    """
    if not BUILD_DIR.is_dir():
        pytest.skip("build/ not present")
    index = client.get("/portal/app/")
    assert index.status_code == 200
    match = re.search(r'/portal/app/assets/([\w\.\-]+\.js)', index.text)
    if not match:
        pytest.skip("no JS asset path in built index.html")
    asset_path = "/portal/app/assets/" + match.group(1)
    r = client.get(asset_path)
    assert r.status_code == 200, (
        f"GET {asset_path} -> {r.status_code}; "
        f"the /portal/app/ mount is probably being shadowed by /portal/"
    )


# ---------- never accidentally serve the source-tree HTML -----------------


def test_portal_app_does_not_serve_source_tree_index_html(client: TestClient):
    """Regression: services/portal/app/index.html at the root references
    /src/main.tsx (the Vite dev entry) and must NOT be what /portal/app/
    serves. FastAPI's StaticFiles would happily serve it if the mount
    pointed at services/portal/app/ instead of services/portal/app/build/.
    """
    if not BUILD_DIR.is_dir():
        pytest.skip("build/ not present")
    r = client.get("/portal/app/")
    body = r.text
    assert '"/src/main.tsx"' not in body, (
        "/portal/app/ is serving the source-tree HTML. main.py is "
        "mounting the source dir, not services/portal/app/build/"
    )

# ---------- F4 noVNC console portal pins --------------------------------


def test_app_source_has_console_card():
    """The F4 ConsoleCard component exists and is exported."""
    console_card = SRC_DIR / "components" / "portal" / "console-card.tsx"
    assert console_card.is_file(), (
        "F4 plan: console-card.tsx must exist"
    )
    src = console_card.read_text()
    assert "export function ConsoleCard" in src


def test_console_card_imports_runtime_dependencies():
    """The card uses canvas, WebSocket, and the toast helper."""
    src = (SRC_DIR / "components" / "portal" / "console-card.tsx").read_text()
    assert "useToasts" in src
    assert "WebSocket" in src
    assert "canvas" in src.lower()


def test_console_card_handles_no_token_path():
    """When the token is missing, the card surfaces a clear error."""
    src = (SRC_DIR / "components" / "portal" / "console-card.tsx").read_text()
    assert "no token" in src.lower()
    # We never assume the token is present.
    assert "getToken()" in src


def test_console_card_hits_the_console_endpoint():
    """The card reads the ticket from the F4 API contract."""
    src = (SRC_DIR / "components" / "portal" / "console-card.tsx").read_text()
    assert "/assets/${pickedAsset.asset_id}/console" in src or (
        "/assets/" in src and "/console" in src
    ), "ConsoleCard must hit the F4 console endpoint"


def test_drill_console_routes_console_open_events():
    """DrillConsole passes an onOpenConsole handler to AssetsCard and
    renders ConsoleCard when an asset is picked."""
    drill = (SRC_DIR / "components" / "portal" / "drill-console.tsx").read_text()
    assert "ConsoleCard" in drill
    assert "pickedAsset" in drill
    assert "onOpenConsole" in drill


def test_assets_card_has_terminal_button_for_running_vms():
    """Open console button only shows for running assets (so we have
    a vmid + PVE ticket)."""
    src = (SRC_DIR / "components" / "portal" / "assets-card.tsx").read_text()
    assert 'onOpenConsole' in src
    assert 'Terminal' in src, (
        "AssetsCard must import Terminal from lucide-react for the "
        "console button"
    )
    # The button is conditional on running status — important since
    # only running VMs can have VNC tickets.
    assert "pve_vmid" in src and "running" in src


def test_portal_bundle_under_budget_after_f4():
    """F4 adds the console WS client + helper code; bundle must
    stay under the 280 KB budget. We pin this every plan that
    touches the portal."""
    assets = BUILD_DIR / "assets"
    if not assets.is_dir():
        pytest.skip("build/ not present")
    js_files = [a for a in assets.glob("*.js") if ".map" not in a.name]
    total = sum(p.stat().st_size for p in js_files)
    assert total < 280 * 1024, (
        f"F4 portal bundle grew to {total/1024:.1f} KB; "
        "expected <280 KB"
    )


def test_console_card_typed_for_run_and_asset():
    """The ConsoleCard props mirror the F4 API contract: pickedRunId
    + pickedAsset of {asset_id, role?}. Pin the shape so a future
    refactor of AssetRef doesn't silently break RunInspector."""
    src = (SRC_DIR / "components" / "portal" / "console-card.tsx").read_text()
    assert "interface AssetRef" in src
    assert "asset_id: number" in src
    assert "role?: string" in src
    assert "ConsoleTicket" in src


# ---------- F6 multi-team leaderboard portal pins -----------------------


def test_app_source_has_leaderboard_card():
    """F6: the LeaderboardCard component exists and is exported."""
    card = SRC_DIR / "components" / "portal" / "leaderboard-card.tsx"
    assert card.is_file(), "F6 plan: leaderboard-card.tsx must exist"
    src = card.read_text()
    assert "export function LeaderboardCard" in src


def test_leaderboard_card_typed_for_team_payload():
    """The LeaderboardCard reads the F6 leaderboard API contract."""
    card = (SRC_DIR / "components" / "portal" / "leaderboard-card.tsx").read_text()
    assert "leaderboard" in card.lower()
    # Required keys per team
    for k in ("rank", "team_id", "name", "color", "score"):
        assert k in card, f"LeaderboardCard missing key {k!r}"
    # It hits the /leaderboard endpoint
    assert "/leaderboard" in card


def test_leaderboard_card_renders_first_place_crown():
    """The #1 team shows a Crown icon."""
    card = (SRC_DIR / "components" / "portal" / "leaderboard-card.tsx").read_text()
    assert "Crown" in card
    assert "first place" in card.lower() or "isFirst" in card


def test_leaderboard_card_handles_empty_teams():
    """Empty teams[] surfaces a friendly message."""
    card = (SRC_DIR / "components" / "portal" / "leaderboard-card.tsx").read_text()
    assert "No teams yet" in card


def test_portal_bundle_under_budget_after_f6():
    """F6 adds the leaderboard card; bundle must stay under 280 KB."""
    assets = BUILD_DIR / "assets"
    if not assets.is_dir():
        pytest.skip("build/ not present")
    js_files = [a for a in assets.glob("*.js") if ".map" not in a.name]
    total = sum(p.stat().st_size for p in js_files)
    assert total < 280 * 1024, (
        f"F6 portal bundle grew to {total/1024:.1f} KB; expected <280 KB"
    )
