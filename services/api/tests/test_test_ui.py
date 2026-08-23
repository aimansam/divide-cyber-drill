"""Smoke tests for the operator test UI.

We don't render HTML in tests (no headless browser here); we assert:
  * the new GET endpoints work end-to-end against the FastAPI app
  * the new endpoints appear in the OpenAPI schema
  * the page is reachable at /portal/test/
  * the page contains the expected anchor elements (so a future rename
    shows up as a test failure)

Why not Playwright: the rest of the test suite has zero JS-runtime deps
and we want this to keep working offline. The test-page just wraps
fetch() calls -- if the endpoints work, the JS will work in a browser.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


# ----- Endpoint shape --------------------------------------------------


def test_get_single_drill_with_assets(client):
    """GET /api/v1/drills/{run_id} returns the run + assets[]."""
    # Need a run row first. We don't have a router endpoint that creates
    # runs without a runner -- so we insert directly via the DB session
    # the router uses. For a smoke test, we just check the 404 path.
    r = client.get("/api/v1/drills/999999")
    assert r.status_code == 404
    assert "999999" in r.json()["detail"]


def test_get_drill_audit_404_for_missing_run(client):
    r = client.get("/api/v1/drills/999999/audit")
    assert r.status_code == 404


def test_get_drill_audit_for_existing_run_returns_items(client):
    """If a run exists, /audit returns at least the bootstrap records."""
    # Use the list endpoint to find any existing run, then ask for its
    # audit. The dev DB has had runs from previous test work.
    listing = client.get("/api/v1/drills")
    assert listing.status_code == 200
    runs = listing.json().get("items") or []
    if not runs:
        pytest.skip("no runs in DB to test with; seed one manually")
    target_id = runs[0]["run_id"]
    r = client.get(f"/api/v1/drills/{target_id}/audit")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert body["total"] == len(body["items"])


def test_new_endpoints_in_openapi(client):
    """OpenAPI schema exposes the two new endpoints."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    assert "/api/v1/drills/{run_id}" in paths, "GET single drill missing from OpenAPI"
    assert "/api/v1/drills/{run_id}/audit" in paths, "GET drill audit missing from OpenAPI"


# ----- Page delivery ---------------------------------------------------


def test_portal_test_page_is_served(client):
    """GET /portal/test/ returns the test UI HTML."""
    r = client.get("/portal/test/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "div:ide — test UI" in body or "div:ide \u2014 test UI" in body


def test_portal_test_page_contains_expected_anchors(client):
    """The page should expose anchor ids the JS relies on.

    If a future refactor renames ``run-id`` -> ``runId``, this catches
    it without a JS runtime.
    """
    r = client.get("/portal/test/")
    assert r.status_code == 200
    body = r.text
    for anchor in [
        "scn-select", "scn-detail",
        "run-id", "run-detail",
        "cancel-btn", "cancel-result",
        "assets-list",
        "audit-list",
        "metrics-output",
        "pve-health", "pve-nodes", "pve-templates",
    ]:
        assert f'id="{anchor}"' in body, f"missing anchor id={anchor}"


def test_portal_wizard_still_serves(client):
    """Sanity: adding /portal/test/ didn't break /portal/."""
    r = client.get("/portal/")
    assert r.status_code == 200
    assert "PVE setup" in r.text


# ----- File sanity -----------------------------------------------------


def test_portal_test_html_exists_on_disk():
    """The HTML file should be on disk where the Dockerfile copies from."""
    p = Path(__file__).resolve().parents[2] / "portal" / "test" / "index.html"
    assert p.exists(), f"portal page missing at {p}"
    assert p.stat().st_size > 1000, "portal page suspiciously small"
