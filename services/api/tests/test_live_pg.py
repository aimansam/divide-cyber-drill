"""Tests for the live_pg test infrastructure.

These tests verify the marker plumbing works:
  * live_pg-marked tests are SKIPPED by default (SQLite mode).
  * live_pg-marked tests RUN when DIVIDE_TEST_LIVE_PG is set.

The real value of `live_pg` is in existing tests that *only* make sense
against real Postgres (e.g. enum case-sensitivity, JSONB operators). New
ones can be added by tagging them with `@pytest.mark.live_pg`.
"""
from __future__ import annotations

import pytest


@pytest.mark.live_pg
def test_live_pg_marker_runs_against_postgres():
    """A trivial live_pg test.

    When run against the live PG conftest, this passes. When run under
    the default SQLite mode, conftest's `pytest_collection_modifyitems`
    skips it. Either way, CI stays green; if you DO have a live PG,
    the test will execute and tell you the marker is wired correctly.
    """
    assert True


def test_live_pg_helper_resolves_truthy_env(monkeypatch):
    """`_live_pg_url()` returns the URL when DIVIDE_TEST_LIVE_PG is set."""
    import importlib.util

    monkeypatch.setenv("DIVIDE_TEST_LIVE_PG", "1")
    monkeypatch.setenv(
        "DIVIDE_TEST_LIVE_PG_URL", "postgresql+asyncpg://u:p@h:5432/db"
    )

    spec = importlib.util.spec_from_file_location(
        "_divide_conftest",
        "services/api/tests/conftest.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    url = mod._live_pg_url()
    assert url and url.startswith("postgresql")


def test_live_pg_helper_returns_none_when_unset(monkeypatch):
    import importlib.util

    monkeypatch.delenv("DIVIDE_TEST_LIVE_PG", raising=False)
    monkeypatch.delenv("DIVIDE_TEST_LIVE_PG_URL", raising=False)

    spec = importlib.util.spec_from_file_location(
        "_divide_conftest",
        "services/api/tests/conftest.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._live_pg_url() is None
