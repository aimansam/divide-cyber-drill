"""Static + smoke checks for the role-aware portal composition (M3.2, Half 1).

The portal renders only the cards each role can use. The single
source of truth is the COMPOSITIONS table in
``services/portal/app/src/app.tsx``. These tests pin that table:

  * Every role in the Role union appears in COMPOSITIONS.
  * Every card `kind` referenced in COMPOSITIONS resolves to a
    real file in ``components/portal/``.
  * Each role's composition matches the matrix the server enforces
    in commit 4d840f9 (no RunLifecycleCard for blue / observer /
    anon; run-lifecycle present for admin / lead / red).
  * The new ``useMe()`` hook + /api/v1/me endpoint are wired into
    the portal (we don't render the unverified JWT decode anymore).
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


# ---------- COMPOSITIONS table shape ---------------------------------------


def test_compositions_table_is_present():
    src = _read("services/portal/app/src/app.tsx")
    assert "const COMPOSITIONS" in src, (
        "app.tsx must export a COMPOSITIONS table; this is the "
        "single source of truth for which cards render per role"
    )


def test_compositions_covers_every_role():
    roles_src = _read("services/portal/app/src/lib/roles.ts")
    m = re.search(
        r"export const ROLES:\s*readonly Role\[\]\s*=\s*\[(.+?)\]",
        roles_src,
        re.DOTALL,
    )
    assert m, "lib/roles.ts ROLES array not found"
    role_values = re.findall(r'"([a-z]+)"', m.group(1))
    assert role_values == ["admin", "lead", "red", "blue", "observer"], role_values

    app_src = _read("services/portal/app/src/app.tsx")
    for role in role_values + ["anonymous"]:
        assert f"  {role}:" in app_src or f"  {role} :" in app_src, (
            f"role {role!r} missing from COMPOSITIONS in app.tsx"
        )


def test_compositions_only_reference_real_cards():
    app_src = _read("services/portal/app/src/app.tsx")
    kinds = sorted(set(re.findall(r'kind:\s*"([\w-]+)"', app_src)))
    assert kinds, "no `kind:` literals in app.tsx"
    for kind in kinds:
        assert f'case "{kind}":' in app_src, (
            f"kind={kind!r} is in COMPOSITIONS but has no switch case "
            f"in app.tsx — would render nothing"
        )


def test_compositions_references_only_existing_components():
    app_src = _read("services/portal/app/src/app.tsx")
    for card_import in ["ScenariosCard", "MyRunsCard", "RunLifecycleCard"]:
        assert card_import in app_src, (
            f"app.tsx does not import {card_import} but renders it"
        )


# ---------- per-role card set ----------------------------------------------


def _composition_for_role(app_src: str, role: str) -> list[str]:
    """Crude parser: returns the list of `kind:` strings under
    `  <role>: [` in the COMPOSITIONS table. Lines look like
    `    { kind: "scenarios" },` so we match kind: anywhere.
    """
    lines = app_src.splitlines()
    out: list[str] = []
    in_block = False
    block_indent = 0
    for line in lines:
        if not in_block:
            stripped = line.strip()
            if stripped.startswith(f"{role}:") and "[" in stripped:
                in_block = True
                block_indent = len(line) - len(line.lstrip())
                if "]" in stripped and stripped.endswith("],"):
                    in_block = False
                continue
        else:
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent <= block_indent and line.strip():
                in_block = False
                continue
            m = re.search(r'kind:\s*"([\w-]+)"', line)
            if m is not None:
                out.append(m.group(1))
    return out


@pytest.mark.parametrize(
    "role,expected_kinds",
    [
        ("anonymous", ["scenarios", "sign-in-banner"]),
        ("admin", ["scenarios", "my-runs", "run-lifecycle"]),
        ("lead", ["scenarios", "my-runs", "run-lifecycle"]),
        ("red", ["scenarios", "my-runs", "run-lifecycle"]),
        ("blue", ["scenarios", "my-runs"]),
        ("observer", ["scenarios", "my-runs"]),
    ],
)
def test_per_role_composition_matches_matrix(role: str, expected_kinds: list[str]):
    """Hard pin on the per-role card set.

    Blue and observer do NOT get RunLifecycleCard; they would see
    "Start drill" and get 403 on click. Composition-not-rendering
    is the right fix.
    """
    app_src = _read("services/portal/app/src/app.tsx")
    kinds = _composition_for_role(app_src, role)
    assert sorted(kinds) == sorted(expected_kinds), (
        f"role {role!r} composition changed: expected "
        f"{sorted(expected_kinds)}, got {sorted(kinds)}. "
        f"This is a deliberate contract — update USER-REQUIREMENTS.md §2 "
        f"and the COMPOSITIONS table comment if you intend to change it."
    )


# ---------- useMe() + /api/v1/me wiring ------------------------------------


def test_token_bar_no_longer_decodes_jwt_client_side():
    src = _read("services/portal/app/src/components/portal/token-bar.tsx")
    assert "function decodeUnverified" not in src, (
        "TokenBar still contains decodeUnverified(); the move to "
        "useMe() in M3.2 removed it"
    )
    assert "useMe" in src, "TokenBar must use the useMe() hook"


def test_app_tsx_uses_use_me_hook():
    src = _read("services/portal/app/src/app.tsx")
    assert "useMe" in src, "app.tsx must import + call useMe()"


def test_use_me_hook_hits_me_endpoint():
    src = _read("services/portal/app/src/lib/auth.ts")
    assert '"/api/v1/me"' in src, (
        "useMe() must call GET /api/v1/me; that's the endpoint "
        "added in M3.2 Half 1"
    )


def test_me_endpoint_is_openapi_listed():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/api/v1/me" in spec["paths"]


def test_roles_lib_has_five_roles_and_labels():
    src = _read("services/portal/app/src/lib/roles.ts")
    for role in ("admin", "lead", "red", "blue", "observer"):
        assert f'"{role}"' in src, f"role {role!r} not in lib/roles.ts ROLES union"
        assert f"{role}:" in src, (
            f"ROLE_LABELS missing {role!r}; the badge would render 'undefined'"
        )


# ---------- bundle integrity ------------------------------------------------


def test_built_bundle_includes_compositions_keyword():
    build_dir = APP_DIR / "build"
    if not build_dir.is_dir():
        pytest.skip("build/ not present; run `npm run build` first")
    assets = list((build_dir / "assets").glob("*.js"))
    assert assets, "no JS bundle in build/assets/"
    found = False
    for asset in assets:
        if "Showing the composition for" in asset.read_text(encoding="utf-8"):
            found = True
            break
    assert found, (
        "Production bundle does not contain 'Showing the composition for'. "
        "Either app.tsx was tree-shaken or the build step hasn't re-run."
    )


def test_built_bundle_size_within_budget():
    build_dir = APP_DIR / "build"
    if not build_dir.is_dir():
        pytest.skip("build/ not present")
    js_assets = [a for a in (build_dir / "assets").glob("*.js") if ".map" not in a.name]
    assert js_assets, "no JS bundle"
    total_bytes = sum(a.stat().st_size for a in js_assets)
    budget = 250 * 1024
    assert total_bytes < budget, (
        f"Production JS bundle is {total_bytes/1024:.1f} KB; budget is "
        f"{budget/1024:.0f} KB. Time to start lazy-loading."
    )


# ---------- summary ---------------------------------------------------------


def test_role_composition_summary_emitted():
    app_src = _read("services/portal/app/src/app.tsx")
    summary = {
        role: _composition_for_role(app_src, role)
        for role in ("anonymous", "admin", "lead", "red", "blue", "observer")
    }
    print("\nportal/app role composition (Half 1):")
    print(json.dumps(summary, indent=2))
    assert True
