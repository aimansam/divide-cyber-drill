"""Static + smoke tests for the F3-prep SignInCard.

The SignInCard is a React component; we can't run a full jsdom
harness from Python. Instead these tests verify:

  * the component file exists and exports SignInCard
  * the component imports `login` from `@/lib/api` (the wired flow)
  * app.tsx imports SignInCard and routes `sign-in-card` to it
  * the anonymous composition includes `sign-in-card`
  * the SignInCard renders the right elements (username field,
    password field, submit button) — by grepping for the right
    testid/aria-label hooks
  * the SignInCard documents 401 / 429 / 422 error handling
  * the API helper `login` is exported from lib/api.ts and POSTs
    to the right path
  * the production bundle stays under 280 KB after SignInCard
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "services" / "portal" / "app"
SRC_DIR = APP_DIR / "src"
CARD_PATH = SRC_DIR / "components" / "portal" / "sign-in-card.tsx"
APP_TSX = SRC_DIR / "app.tsx"
API_TS = SRC_DIR / "lib" / "api.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------- SignInCard file shape ------------------------------------------


def test_sign_in_card_file_exists():
    assert CARD_PATH.is_file(), f"missing: {CARD_PATH}"


def test_sign_in_card_exports_component():
    src = _read(CARD_PATH)
    assert "export function SignInCard" in src, (
        "SignInCard must be a named export so app.tsx can import it"
    )


def test_sign_in_card_imports_login_helper():
    src = _read(CARD_PATH)
    # The component must call the wired login() helper, not raw
    # fetch() to /api/v1/auth/login. That keeps the abstraction.
    assert re.search(r'import\s*\{[^}]*\blogin\b[^}]*\}\s*from\s*"@/lib/api"', src), (
        "SignInCard must import `login` from @/lib/api"
    )


def test_sign_in_card_renders_username_field():
    src = _read(CARD_PATH)
    assert 'id="signin-sub"' in src or 'name="username"' in src or 'id="signin-sub"' in src
    assert 'autoComplete="username"' in src or "autoComplete='username'" in src


def test_sign_in_card_renders_password_field():
    src = _read(CARD_PATH)
    assert 'type="password"' in src or "type='password'" in src
    assert 'autoComplete="current-password"' in src or "autoComplete='current-password'" in src


def test_sign_in_card_renders_submit_button():
    src = _read(CARD_PATH)
    assert 'type="submit"' in src


def test_sign_in_card_handles_401_429_422():
    """All three documented error shapes have to be present in the
    component so the UI surfaces them."""
    src = _read(CARD_PATH)
    assert "401" in src, "SignInCard must handle 401 (invalid credentials)"
    assert "429" in src, "SignInCard must handle 429 (rate limited)"
    assert "422" in src, "SignInCard must handle 422 (validation error)"


def test_sign_in_card_clears_password_after_success():
    """Belt-and-suspenders: don't keep the password in component
    state after the user successfully signs in."""
    src = _read(CARD_PATH)
    assert "setPassword(\"\")" in src or 'setPassword("")' in src, (
        "SignInCard should clear the password field after a successful login"
    )


def test_sign_in_card_emits_token_change():
    """A successful login must call setToken + emitTokenChange so
    useMe() re-fetches and the parent re-renders the authenticated
    layout."""
    src = _read(CARD_PATH)
    assert "setToken" in src, "SignInCard must call setToken()"
    assert "emitTokenChange" in src, "SignInCard must call emitTokenChange()"


# ---------- app.tsx wiring ----------------------------------------------


def test_app_tsx_imports_sign_in_card():
    src = _read(APP_TSX)
    assert "SignInCard" in src, "app.tsx must import SignInCard"
    assert 'from "@/components/portal/sign-in-card"' in src


def test_app_tsx_renders_sign_in_card_in_anonymous_branch():
    """F4-UI moved the SignInCard out of the COMPOSITIONS table
    into a dedicated anonymous branch in app.tsx. SignInCard must
    still render when no token is present."""
    import re

    src = _read(APP_TSX)
    assert "<SignInCard" in src, (
        "SignInCard must render in app.tsx (anonymous branch)"
    )
    # Look for a render path that mentions both `!me` and SignInCard.
    assert re.search(r"!\s*me[\s\S]{0,800}<SignInCard", src), (
        "SignInCard must render in the `!me` branch (anonymous viewer)"
    )


def test_app_tsx_no_longer_uses_compositions_table():
    """F4-UI replaced COMPOSITIONS with view-tab routing. If a
    future change reintroduces COMPOSITIONS it must be deliberate."""
    src = _read(APP_TSX)
    assert "COMPOSITIONS" not in src, (
        "app.tsx must not use the COMPOSITIONS table anymore — "
        "view-tab routing replaces it (F4-UI)"
    )



def test_app_tsx_anonymous_branch_documented():
    """F4-UI: the anonymous branch in app.tsx is the only place
    SignInCard is rendered. Pin that the branch exists and
    references SignInCard, even if its exact name changes."""
    src = _read(APP_TSX)
    assert "<SignInCard" in src, (
        "SignInCard must render in app.tsx"
    )
    # Anonymous branch in F4-UI is the inverse of the authed one.
    assert "SignInCard" in src and ("!me" in src or "! me" in src), (
        "app.tsx must have a non-authed render path that mounts SignInCard"
    )


# ---------- lib/api.ts login/logout helpers -------------------------------


def test_api_ts_exports_login():
    src = _read(API_TS)
    assert "export async function login" in src, (
        "lib/api.ts must export login() helper"
    )


def test_api_ts_exports_logout():
    src = _read(API_TS)
    assert "export async function logout" in src, (
        "lib/api.ts must export logout() helper"
    )


def test_api_ts_login_posts_to_auth_login():
    src = _read(API_TS)
    assert '"/api/v1/auth/login"' in src, (
        "lib/api.ts login() must POST to /api/v1/auth/login"
    )


def test_api_ts_login_response_shape_documented():
    """The LoginResponse interface should declare the shape the
    backend returns, so component code can rely on it."""
    src = _read(API_TS)
    # The interface declares the fields; the helper returns them.
    for field in ("token", "sub", "role", "iat", "exp", "ttl_remaining_s"):
        assert field in src, f"LoginResponse missing field: {field}"


def test_api_ts_logout_clears_token():
    """logout() must clear the localStorage token so the parent
    re-renders the anonymous composition."""
    src = _read(API_TS)
    # Inside the logout function body, look for setToken("").
    m = re.search(
        r"export async function logout\(\).*?\n\}",
        src,
        re.DOTALL,
    )
    assert m, "logout() function not found"
    body = m.group(0)
    assert 'setToken("")' in body or "setToken('')" in body, (
        "logout() must call setToken('') to clear localStorage"
    )


# ---------- bundle size --------------------------------------------------


def test_bundle_size_stays_under_280kb_with_sign_in_card():
    """F3-prep adds SignInCard + login/logout helpers. Bundle
    must stay under the Half-2 280 KB lazy-load budget."""
    build_dir = APP_DIR / "build"
    if not build_dir.is_dir():
        pytest.skip("build/ not present; run `npm run build` first")
    js_assets = [
        a for a in (build_dir / "assets").glob("*.js") if ".map" not in a.name
    ]
    total_bytes = sum(a.stat().st_size for a in js_assets)
    budget = 280 * 1024
    assert total_bytes < budget, (
        f"Production JS bundle is {total_bytes/1024:.1f} KB; budget "
        f"is {budget/1024:.0f} KB. Time to lazy-load cards."
    )


def test_sign_in_card_documented_role_set():
    """The component docstring should mention what the card is for
    so future readers don't have to grep the role matrix."""
    src = _read(CARD_PATH)
    assert "SignInCard" in src and ("F3-prep" in src or "credential" in src.lower()), (
        "SignInCard must self-document its purpose"
    )
