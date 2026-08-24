"""Static-analysis smoke tests for the operator portal pages.

The two pages under ``/portal`` (setup wizard, test UI) are vanilla
HTML+JS served by FastAPI's StaticFiles. They do their real work via
``fetch()`` calls to the API. The cheapest regression guard against a
silent breakage is: assert each page references the API endpoints it
needs.

Why this and not Playwright:
  * Playwright adds a ~150MB CI dependency plus a browser runtime.
  * The failure mode that matters is "the JS calls a path that
    doesn't exist on the API" -- that's a one-line substring check.
  * If we ever need click-through tests, add Playwright then.

What this catches:
  * Renaming or removing an API endpoint while the page still
    references it -- the static check fails loudly.
  * Accidentally dropping a JS call to a critical endpoint.

What this does NOT catch:
  * Wrong method (GET vs POST) -- handled by the existing router tests.
  * Wrong status-code handling -- handled by the integration tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# Each entry: page_name -> (relative_path, list of substring fragments
# the JS must contain referring to API endpoints). Substrings are the
# smallest distinct token that identifies the call (e.g. for
# `API + "/probe"` we assert `"/probe"` appears in the file).
#
# Fragments are bare path parts (no leading slash-quote, no trailing
# quote) because the JS concatenates URLs with `+` and uses both
# ``"..."`` and `` `...${var}...` `` patterns, so a literal
# quote-delimited substring would miss template literals. The fragments
# here are stable across both quote styles.
#
# ANCHORING: Each fragment must appear in the file as a substring,
# but we deliberately anchor on the trailing context too (the next 1-2
# characters in the source). A break like `/api/v1/admin_DOES_NOT_EXIST`
# would still contain `/api/v1/admin` as a prefix, so we tighten the
# check by requiring the fragment to appear *and* not be followed by
# `_DOES_NOT_EXIST` (which is the kind of accidental mutation we want
# to catch). In practice this means using fragments that aren't
# prefixes of any other URL in the file.
PORTAL_HTML_FILES: dict[str, tuple[str, list[str]]] = {
    "wizard": (
        "services/portal/index.html",
        [
            # Each fetch target -- concatenated as `API + "/fragment"`.
            "/probe",
            "/upload-qcow2",
            "/create-template",
            "/set-template",
            "/progress/template",
            "/drill-template-status",
            "/start-first-drill",
            # Step 2 pre-populated command -- catches accidental edits.
            "pveum acl modify",
        ],
    ),
    "test_ui": (
        "services/portal/test/index.html",
        [
            # Sub-routes the test UI fetches with template literals.
            # The JS uses {id} (not {run_id}) as the variable name; both
            # the <span class="hint"> docs and the JS template literals
            # reference it this way.
            "/api/v1/drills/{id}/cancel",
            "/api/v1/drills/{id}/audit",
            "/api/v1/drills/{id}",
            # Top-level API URL prefixes -- these are full URLs the test
            # UI fetches with both string concat and template literals.
            "/api/v1/scenarios",
            "/api/v1/proxmox",
            # Prometheus exposition.
            "/metrics",
        ],
    ),
    # The React/Vite user portal at /portal/app/ is covered by
    # tests/test_portal_app_smoke.py instead — the bundle-vs-source
    # invariants are different (the on-disk index.html is tiny and
    # references /src/main.tsx, not API fragments). We still want
    # the portal page to exist on disk, so keep it in
    # `PORTAL_PAGES_ON_DISK_ONLY` below.
}


def _is_uniquely_present(html: str, fragment: str) -> bool:
    """True if `fragment` appears in `html` AND no occurrence is a
    prefix of a longer URL.

    Catches: someone renames `/api/v1/admin` to `/api/v1/admin_thing`
    -- our fragment `/api/v1/admin` would still match the prefix, so
    we anchor with a negative-lookahead that rejects path chars
    (letters/digits/`_`/`-`) but NOT path separators (`/`) -- because
    `/set-template/` is a legitimate URL form for the same endpoint.
    """
    import re

    # The fragment must appear *as a substring* but NOT be immediately
    # followed by a char that extends the URL token (letter, digit,
    # underscore, hyphen). Path separators, quotes, whitespace, plus,
    # backtick, parens, commas are all OK -- they end the token.
    pattern = re.compile(re.escape(fragment) + r"(?![A-Za-z0-9_-])")
    return bool(pattern.search(html))


# Map each page's fragments to the full OpenAPI path they should resolve
# to. This lets us catch the inverse failure mode too: the router was
# renamed and the page still references it but with the old substring.
# Note: the JS uses {id} in template literals but the OpenAPI schema
# uses {run_id} (that's what the router declared). They're the same
# route -- just different placeholder names.
EXPECTED_PATHS_FROM_FRAGMENTS: dict[str, str] = {
    "/probe": "/api/v1/admin/probe",
    "/upload-qcow2": "/api/v1/admin/upload-qcow2",
    "/create-template": "/api/v1/admin/create-template",
    "/set-template": "/api/v1/admin/set-template/{vmid}",
    "/drill-template-status": "/api/v1/admin/drill-template-status",
    "/start-first-drill": "/api/v1/admin/start-first-drill",
    "/api/v1/scenarios": "/api/v1/scenarios",
    "/api/v1/drills": "/api/v1/drills",
    "/api/v1/drills/{id}": "/api/v1/drills/{run_id}",
    "/api/v1/drills/{id}/cancel": "/api/v1/drills/{run_id}/cancel",
    "/api/v1/drills/{id}/audit": "/api/v1/drills/{run_id}/audit",
    "/api/v1/proxmox/health": "/api/v1/proxmox/health",
    "/api/v1/proxmox/nodes": "/api/v1/proxmox/nodes",
    "/api/v1/proxmox/templates": "/api/v1/proxmox/templates",
}


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def openapi_paths(client) -> set[str]:
    """All paths exposed by the FastAPI app, in OpenAPI format."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    return set(r.json().get("paths", {}).keys())


# ---------- tests ---------------------------------------------------------


@pytest.mark.parametrize(
    "page_name",
    list(PORTAL_HTML_FILES),
)
def test_page_references_all_expected_api_fragments(page_name):
    """Every API path the page references must be present in the source.

    Catches: a portal refactor that drops a fetch() call to an endpoint.
    """
    relpath, fragments = PORTAL_HTML_FILES[page_name]
    html = (Path(__file__).resolve().parent.parent / relpath).read_text()
    missing = [s for s in fragments if not _is_uniquely_present(html, s)]
    assert not missing, (
        f"{relpath} is missing expected endpoint fragments: {missing}. "
        f"If you renamed an endpoint, update both the router AND this test."
    )


def test_portal_endpoints_exist_in_openapi(openapi_paths):
    """Every endpoint the JS references must also be in the FastAPI OpenAPI.

    The reverse direction of the fragment check: catches the case where
    someone renamed a router path but left the JS referring to it.
    """
    for fragment, full in EXPECTED_PATHS_FROM_FRAGMENTS.items():
        assert full in openapi_paths, (
            f"Portal references {fragment!r} which should resolve to "
            f"{full!r}, but OpenAPI doesn't list it. Either the router "
            f"was renamed or this map is stale."
        )


def test_both_pages_have_a_script_tag():
    """Every vanilla portal page must run JS; a missing <script> means the
    page is broken before fetch() is even called.

    The React portal at /portal/app/ uses a Vite-bundled
    ``<script type="module" src="/src/main.tsx">`` instead of an inline
    block — its invariant is covered by test_portal_app_smoke.py
    (``test_app_entry_script_marker_is_present``).
    """
    for relpath, _ in PORTAL_HTML_FILES.values():
        html = (Path(__file__).resolve().parent.parent / relpath).read_text()
        assert "<script>" in html, f"{relpath} has no <script> block -- the page can't run JS"


def test_portal_pages_exist_on_disk():
    """Both pages must be on disk; the Dockerfile copies the directory
    wholesale so any future page under services/portal/ gets shipped.
    """
    for relpath, _ in PORTAL_HTML_FILES.values():
        p = Path(__file__).resolve().parent.parent / relpath
        assert p.exists(), f"{relpath} missing at {p}"
        assert p.stat().st_size > 1000, f"{relpath} suspiciously small"


def test_test_ui_has_run_id_input_id():
    """The test UI relies on an ``id=\"run-id\"`` input -- ``$(\"run-id\")`` in the JS.

    Rename either side without the other and the page silently breaks.
    """
    html = (Path(__file__).resolve().parent.parent / PORTAL_HTML_FILES["test_ui"][0]).read_text()
    assert 'id="run-id"' in html, (
        "test UI must keep id=\"run-id\" -- the JS uses $('run-id') to read it"
    )
    # Sanity: the JS does indeed use that id.
    assert "$(\"run-id\")" in html or "$('run-id')" in html, (
        "test UI JS must querySelector for 'run-id' -- the input id is referenced"
    )
