"""Tests for app.core.auth (token sign + verify + FastAPI dependency).

Covers:
  * sign_token / verify_token round-trip
  * expiry rejection
  * tampered signature rejection
  * malformed tokens
  * FastAPI dependency: current_token sets request.state.token
  * require_token returns 401 when missing
  * require_token returns TokenData when valid
  * issue_token CLI outputs a single valid token
"""
from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_auth_cache():
    """Reset the per-process fallback secret cache between tests.

    Without this, tests that hit the random-fallback branch share a
    secret (the cache survives across tests in the same process),
    which is fine for the in-process contract but makes test ordering
    matter for the "wrong secret" rejection tests.
    """
    from app.core import auth

    auth._RANDOM_FALLBACK_SECRET = None
    yield
    auth._RANDOM_FALLBACK_SECRET = None


# ---------- sign + verify --------------------------------------------------


def test_round_trip_sign_then_verify():
    from app.core.auth import sign_token, verify_token

    tok = sign_token("alice", "trainee", 3600)
    data = verify_token(tok)
    assert data.sub == "alice"
    assert data.role == "trainee"
    assert data.exp > data.iat
    assert data.exp - data.iat == 3600


def test_round_trip_admin_role():
    from app.core.auth import sign_token, verify_token

    tok = sign_token("bob", "admin", 60)
    data = verify_token(tok)
    assert data.role == "admin"


def test_expired_token_rejected():
    from app.core.auth import AuthError, sign_token, verify_token

    tok = sign_token("x", "y", 1)
    time.sleep(2)
    with pytest.raises(AuthError) as ei:
        verify_token(tok)
    assert "expired" in str(ei.value).lower()


def test_tampered_signature_rejected():
    from app.core.auth import AuthError, sign_token, verify_token

    tok = sign_token("alice", "trainee", 3600)
    payload_b64, sig_b64 = tok.rsplit(".", 1)
    # Flip a char in the middle of the signature -- not the last one,
    # because base64's last 6-bit chunk can pad with '=' which means
    # the rightmost bits are padding-only and substituting there can
    # produce a byte-identical decoded signature. Mid-string changes
    # are guaranteed to flip at least one decoded bit.
    mid = len(sig_b64) // 2
    original = sig_b64[mid]
    flipped = "B" if original != "B" else "C"
    bad_sig = sig_b64[:mid] + flipped + sig_b64[mid + 1 :]
    bad = f"{payload_b64}.{bad_sig}"
    with pytest.raises(AuthError) as ei:
        verify_token(bad)
    assert "signature" in str(ei.value).lower()


def test_malformed_tokens_rejected():
    from app.core.auth import AuthError, verify_token

    for bad in ["no-dot", "", ".", "a.", ".sig", "a.b.c"]:
        with pytest.raises(AuthError):
            verify_token(bad)


def test_sign_rejects_empty_sub():
    from app.core.auth import sign_token

    with pytest.raises(ValueError, match="sub"):
        sign_token("", "trainee", 60)


def test_sign_rejects_zero_ttl():
    from app.core.auth import sign_token

    with pytest.raises(ValueError, match="ttl"):
        sign_token("alice", "trainee", 0)


def test_sign_rejects_non_positive_ttl():
    from app.core.auth import sign_token

    with pytest.raises(ValueError):
        sign_token("alice", "trainee", -10)


def test_token_data_is_expired_helper():
    from app.core.auth import TokenData

    t = TokenData(sub="x", role="y", iat=0, exp=10)
    assert t.is_expired(now=5) is False
    assert t.is_expired(now=10) is True
    assert t.is_expired(now=100) is True


def test_secret_is_stable_within_process():
    """sign + verify in the same process should always agree."""
    from app.core.auth import _signing_secret, sign_token, verify_token

    s1 = _signing_secret()
    s2 = _signing_secret()
    assert s1 == s2
    tok = sign_token("a", "b", 60)
    verify_token(tok)  # would raise if the secret had changed


# ---------- FastAPI dependency ---------------------------------------------


@pytest.fixture
def app():
    from app.core.auth import current_token, require_token

    app = FastAPI()

    @app.get("/optional")
    async def optional(token=Depends(current_token)):
        return {"sub": token.sub if token else None}

    @app.get("/required")
    async def required(token=Depends(require_token)):
        return {"sub": token.sub}

    return app


def test_current_token_returns_none_when_header_missing(app):
    client = TestClient(app)
    r = client.get("/optional")
    assert r.status_code == 200
    assert r.json() == {"sub": None}


def test_current_token_returns_token_when_valid(app):
    from app.core.auth import sign_token

    client = TestClient(app)
    tok = sign_token("alice", "trainee", 3600)
    r = client.get("/optional", headers={"X-Divide-Token": tok})
    assert r.status_code == 200
    assert r.json() == {"sub": "alice"}


def test_current_token_returns_401_when_invalid(app):
    client = TestClient(app)
    r = client.get("/optional", headers={"X-Divide-Token": "not-a-real-token"})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_require_token_returns_401_when_missing(app):
    client = TestClient(app)
    r = client.get("/required")
    assert r.status_code == 401


def test_require_token_returns_sub_when_valid(app):
    from app.core.auth import sign_token

    client = TestClient(app)
    tok = sign_token("alice", "admin", 3600)
    r = client.get("/required", headers={"X-Divide-Token": tok})
    assert r.status_code == 200
    assert r.json() == {"sub": "alice"}


# ---------- CLI -----------------------------------------------------------


def test_issue_token_cli_outputs_a_valid_token(tmp_path, monkeypatch):
    """End-to-end: run the CLI, paste the token back into verify_token.

    Proves the CLI prints parseable tokens.

    Why we set DIVIDE_TOKEN_DEV_SECRET: the test process and the
    subprocess both use the random-fallback branch (no proxmox
    secret configured in CI). Each gets its own random secret by
    default; passing a fixed secret via env makes them agree.
    """
    import subprocess
    import sys

    shared_secret = "test-fixture-secret-1234"
    env = {
        **__import__("os").environ,
        "PYTHONPATH": "services/api",
        "DIVIDE_TOKEN_DEV_SECRET": shared_secret,
    }
    r = subprocess.run(
        [
            sys.executable,
            "tools/issue_token.py",
            "--user",
            "alice",
            "--role",
            "trainee",
            "--ttl",
            "1h",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=".",
        check=False,
    )
    assert r.returncode == 0, f"CLI failed: {r.stderr}"
    tok = r.stdout.strip()
    assert "." in tok, f"CLI output doesn't look like a token: {tok!r}"

    # Set the test process to the same secret so verify_token can decode.
    from app.core import auth as auth_mod

    auth_mod._RANDOM_FALLBACK_SECRET = shared_secret.encode("utf-8")

    from app.core.auth import verify_token

    data = verify_token(tok)
    assert data.sub == "alice"
    assert data.role == "trainee"


def test_issue_token_cli_ttl_formats(monkeypatch):
    """Verify the TTL parser handles s/m/h/d suffixes + bare seconds."""
    import subprocess
    import sys

    shared_secret = "test-fixture-secret-ttl"
    env = {
        **__import__("os").environ,
        "PYTHONPATH": "services/api",
        "DIVIDE_TOKEN_DEV_SECRET": shared_secret,
    }
    # Sync the test process to the same secret.
    from app.core import auth as auth_mod

    auth_mod._RANDOM_FALLBACK_SECRET = shared_secret.encode("utf-8")

    for ttl, expected_seconds in [
        ("30", 30),
        ("5m", 300),
        ("2h", 7200),
        ("1d", 86400),
    ]:
        r = subprocess.run(
            [
                sys.executable,
                "tools/issue_token.py",
                "--user",
                "x",
                "--ttl",
                ttl,
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=".",
            check=False,
        )
        assert r.returncode == 0, f"CLI failed for ttl={ttl}: {r.stderr}"
        from app.core.auth import verify_token

        data = verify_token(r.stdout.strip())
        actual = data.exp - data.iat
        assert actual == expected_seconds, f"ttl={ttl}: got {actual}s, expected {expected_seconds}s"


def test_issue_token_cli_rejects_zero_ttl():
    import subprocess
    import sys

    env = {**__import__("os").environ, "PYTHONPATH": "services/api"}
    r = subprocess.run(
        [sys.executable, "tools/issue_token.py", "--user", "x", "--ttl", "0"],
        capture_output=True, text=True, env=env, cwd=".", check=False,
    )
    assert r.returncode != 0
    # The CLI surfaces the validation error to stderr (or stdout).
    combined = (r.stdout + r.stderr).lower()
    assert "ttl" in combined or "positive" in combined


def test_issue_token_cli_rejects_garbage_ttl():
    import subprocess
    import sys

    env = {**__import__("os").environ, "PYTHONPATH": "services/api"}
    r = subprocess.run(
        [sys.executable, "tools/issue_token.py", "--user", "x", "--ttl", "bogus"],
        capture_output=True, text=True, env=env, cwd=".", check=False,
    )
    assert r.returncode != 0
