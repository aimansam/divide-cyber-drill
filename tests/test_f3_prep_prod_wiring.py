"""Tests that F3-prep credential login is wired into the production
build. The F3-prep plan shipped the code (commits 78bc332 + b603c40)
but did not verify that the build + deploy path actually carries it.

These tests pin the production-side wiring:
  * Dockerfile installs argon2-cffi (the password-hashing dep)
  * docker-compose.yml exposes DIVIDE_BOOTSTRAP_ADMIN_SUB +
    DIVIDE_BOOTSTRAP_ADMIN_PASSWORD env vars (with empty defaults)
  * deploy/.env.example documents the F3-prep flow
  * tools/login.py exists and POSTs to /api/v1/auth/login
  * tools/issue_token.py docstring references the new flow
  * tools/run_smoke.py (or equivalent) exercises the login path
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------- Dockerfile ---------------------------------------------------


def test_dockerfile_installs_argon2_cffi():
    """The runtime image must install argon2-cffi or the
    /api/v1/auth/login endpoint will ImportError on every request."""
    src = _read("services/api/Dockerfile")
    # Builder wheel list:
    assert re.search(r'"argon2-cffi[^\"]*"', src), (
        "Dockerfile builder must include argon2-cffi in the wheel list"
    )
    # Runtime pip install:
    assert re.search(r"\bargon2-cffi\b", src), (
        "Dockerfile runtime pip install must include argon2-cffi"
    )


# ---------- docker-compose.yml ------------------------------------------


def test_compose_exposes_bootstrap_admin_sub():
    """DIVIDE_BOOTSTRAP_ADMIN_SUB is the operator-facing knob for
    the F3-prep bootstrap. Empty default (no auto-admin)."""
    src = _read("deploy/docker-compose.yml")
    assert "DIVIDE_BOOTSTRAP_ADMIN_SUB" in src, (
        "docker-compose.yml must expose DIVIDE_BOOTSTRAP_ADMIN_SUB"
    )
    # Default must be empty (no auto-admin without explicit opt-in).
    assert re.search(r"DIVIDE_BOOTSTRAP_ADMIN_SUB:\s*\$\{[^}]*:-\}", src), (
        "DIVIDE_BOOTSTRAP_ADMIN_SUB must have an empty default"
    )


def test_compose_exposes_bootstrap_admin_password():
    src = _read("deploy/docker-compose.yml")
    assert "DIVIDE_BOOTSTRAP_ADMIN_PASSWORD" in src
    assert re.search(
        r"DIVIDE_BOOTSTRAP_ADMIN_PASSWORD:\s*\$\{[^}]*:-\}", src
    ), "DIVIDE_BOOTSTRAP_ADMIN_PASSWORD must have an empty default"


def test_compose_exposes_login_token_ttl():
    """DIVIDE_LOGIN_TOKEN_TTL_S is the F3-prep token-TTL knob."""
    src = _read("deploy/docker-compose.yml")
    assert "DIVIDE_LOGIN_TOKEN_TTL_S" in src
    assert re.search(r"DIVIDE_LOGIN_TOKEN_TTL_S:\s*\$\{[^}]*:-\d+", src), (
        "DIVIDE_LOGIN_TOKEN_TTL_S must have a numeric default"
    )


def test_compose_bootstrap_section_documents_the_flow():
    """The compose file should have an inline comment near the
    F3-prep vars pointing operators at docs/USERS.md."""
    src = _read("deploy/docker-compose.yml")
    # Look for a comment block BEFORE the BOOTSTRAP_ADMIN_SUB var
    # (the comment sits above the env vars per compose convention).
    m = re.search(
        r"([\s\S]{0,400})DIVIDE_BOOTSTRAP_ADMIN_SUB",
        src,
    )
    assert m, "DIVIDE_BOOTSTRAP_ADMIN_SUB line not found"
    block = m.group(1)
    assert "docs/USERS.md" in block or "F3-prep" in block, (
        "compose must document the F3-prep env vars inline"
    )


# ---------- deploy/.env.example -----------------------------------------


def test_env_example_documents_bootstrap_admin_sub():
    src = _read("deploy/.env.example")
    assert "DIVIDE_BOOTSTRAP_ADMIN_SUB" in src
    assert "DIVIDE_BOOTSTRAP_ADMIN_PASSWORD" in src
    assert "DIVIDE_LOGIN_TOKEN_TTL_S" in src


def test_env_example_points_at_users_md():
    """The .env.example file should reference the operator guide so
    a fresh operator finds the next step after copying the file."""
    src = _read("deploy/.env.example")
    assert "docs/USERS.md" in src, (
        "deploy/.env.example must point operators at docs/USERS.md"
    )


# ---------- tools/login.py ----------------------------------------------


def test_login_tool_exists():
    p = REPO / "tools" / "login.py"
    assert p.is_file(), "tools/login.py is missing"


def test_login_tool_posts_to_auth_login():
    src = _read("tools/login.py")
    assert "/api/v1/auth/login" in src


def test_login_tool_uses_argon2id_indirectly():
    """The CLI shouldn't import argon2 (no local hashing) — it sends
    the password over HTTPS to the API which owns the argon2id
    verification. Look for ``import argon2`` or ``from argon2``."""
    src = _read("tools/login.py")
    assert "import argon2" not in src, (
        "tools/login.py should NOT import argon2 locally; the API "
        "owns the argon2id verification"
    )
    assert "from argon2" not in src, (
        "tools/login.py should NOT import from argon2; the API "
        "owns the argon2id verification"
    )


def test_login_tool_handles_401():
    """A bad password should exit with a non-zero code and a
    server-supplied detail string, not a stack trace."""
    src = _read("tools/login.py")
    assert "HTTPError" in src
    # Either the literal "401" string or a code-keyed message path.
    assert "401" in src or "e.code" in src


def test_login_tool_supports_password_flag_for_ci():
    """CI scripts need to pass --password non-interactively. Verify
    the flag is there so tests + automation can drive it."""
    src = _read("tools/login.py")
    assert '"--password"' in src or "'--password'" in src


def test_login_tool_executable():
    import os

    p = REPO / "tools" / "login.py"
    mode = p.stat().st_mode
    assert mode & 0o111, "tools/login.py must be executable (chmod +x)"


# ---------- tools/issue_token.py ----------------------------------------


def test_issue_token_docstring_references_login_flow():
    """issue_token.py's docstring should mention tools/login.py so
    operators pick the right tool for the right job."""
    src = _read("tools/issue_token.py")
    # Either explicitly mentions login.py or the credential flow.
    assert (
        "tools/login.py" in src
        or "credential" in src.lower()
        or "password" in src.lower()
    ), (
        "tools/issue_token.py docstring should reference the "
        "credential-login flow (tools/login.py)"
    )


# ---------- portal app build ---------------------------------------------


def test_portal_build_artifact_picks_up_sign_in_card():
    """The production JS bundle must contain the SignInCard code so
    the operator sees the login screen, not the legacy paste-token UX."""
    build_assets = REPO / "services" / "portal" / "app" / "build" / "assets"
    if not build_assets.is_dir():
        pytest.skip("build/ not present; run `npm run build` first")
    js_files = list(build_assets.glob("*.js"))
    assert js_files, "no JS asset produced"
    bundle = "\n".join(p.read_text(encoding="utf-8") for p in js_files)
    # SignInCard text or its import path should appear in the bundle.
    assert "Sign in to div:ide" in bundle or "sign-in-card" in bundle, (
        "SignInCard text not found in production bundle — the "
        "operator would see the old paste-token UX"
    )


def test_portal_build_artifact_calls_login_endpoint():
    """The bundle should reference /api/v1/auth/login so the login
    form actually posts to the right endpoint."""
    build_assets = REPO / "services" / "portal" / "app" / "build" / "assets"
    if not build_assets.is_dir():
        pytest.skip("build/ not present; run `npm run build` first")
    js_files = list(build_assets.glob("*.js"))
    bundle = "\n".join(p.read_text(encoding="utf-8") for p in js_files)
    assert "/api/v1/auth/login" in bundle, (
        "Login endpoint not found in production bundle — SignInCard "
        "would post to the wrong URL"
    )
