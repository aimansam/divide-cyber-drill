"""Tests for the CORS allowlist (L2 2.10).

CORS is the runtime envelope around the API. A misconfiguration here
either blocks the user-portal (if it's too tight) or opens it up to
attackers (if it's too loose). The allowlist is the explicit list from
``DIVIDE_CORS_ALLOW_ORIGINS`` (comma-separated). The default is local-
only; every deployment overrides.

What we assert:
  * Allowed origin → response carries the ``Access-Control-Allow-Origin``
    echo header (browser permits the cross-origin response).
  * Forbidden origin → response does NOT carry that header (browser
    drops the response on the floor; request still hits API; no JS can
    read it — correct posture).
  * Empty allowlist → no origin is permitted (fail closed).

We exercise the preflight (``OPTIONS``) path because that is where the
browser fails first.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def _new_client():
    """Build a fresh FastAPI app + TestClient after clearing cached config.

    The CORS middleware captures its ``allow_origins`` list at the
    moment ``create_app()`` runs. The CORS attribute is a list (not a
    callable), so re-creating the app per test is the only way to
    read the latest env var.
    """
    from app.core.config import get_settings
    from app.db import session as session_module
    from app.services import db as db_module

    get_settings.cache_clear()
    db_module._engine = None
    session_module._session_maker = None

    import app.main as _app_main

    importlib.reload(_app_main)
    return TestClient(_app_main.app)


@pytest.fixture
def with_cors(monkeypatch):
    """Yield a callable that builds a fresh client after monkey-patching
    ``DIVIDE_CORS_ALLOW_ORIGINS``. ``monkeypatch`` undoes itself at the
    end of each test, so cross-test pollution is impossible.
    """

    def _make(origins: str | None):
        if origins is None:
            monkeypatch.delenv("DIVIDE_CORS_ALLOW_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("DIVIDE_CORS_ALLOW_ORIGINS", origins)
        return _new_client()

    return _make


def test_allowed_origin_preflight_gets_echo_header(with_cors):
    """Preflight from an allowed origin gets the allow-origin echo."""
    with with_cors("http://portal.example.com, http://ops.example.com") as c:
        r = c.options(
            "/healthz",
            headers={
                "Origin": "http://portal.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.headers.get("access-control-allow-origin") == "http://portal.example.com"


def test_forbidden_origin_preflight_has_no_allow_header(with_cors):
    """Preflight from a non-listed origin does NOT echo the origin."""
    with with_cors("http://portal.example.com") as c:
        r = c.options(
            "/healthz",
            headers={
                "Origin": "http://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") is None


def test_empty_origin_list_blocks_all_cross_origin(with_cors):
    """Explicit empty list → no origin permitted (fail closed)."""
    with with_cors("") as c:
        r = c.options(
            "/healthz",
            headers={
                "Origin": "http://portal.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") is None


def test_origins_list_is_parsed_from_comma_separated_env():
    """Unit-test the parser directly.

    ``validation_alias="DIVIDE_CORS_ALLOW_ORIGINS"`` makes pydantic-
    settings look up env by that alias. Pass the kwarg via the alias.
    """
    cases = [
        ("", []),
        ("http://a.example", ["http://a.example"]),
        ("http://a.example,http://b.example", ["http://a.example", "http://b.example"]),
        ("  http://a.example , , http://b.example  ", ["http://a.example", "http://b.example"]),
    ]
    for raw, expected in cases:
        s = __import__("app.core.config", fromlist=["Settings"]).Settings(
            DIVIDE_CORS_ALLOW_ORIGINS=raw
        )
        assert s.cors_allow_origins == expected, f"raw={raw!r} -> {s.cors_allow_origins!r}"