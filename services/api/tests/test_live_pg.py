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


@pytest.mark.live_pg
def test_postgres_enum_types_match_model_declarations() -> None:
    """Q4 regression: every enum declared in models.py must exist as
    a PostgreSQL type after ``alembic upgrade head``.

    Migration 0006 (exercises) declared ``exercises.status`` as plain
    VARCHAR but the SQLAlchemy model declares it as
    ``Enum(ExerciseStatus, name="exercise_status")``. On every Postgres
    install that mismatch means the ``exercise_status`` type is never
    created, and any insert crashes with ``type "exercise_status"
    does not exist``. SQLite hides this because it stores enums as TEXT.

    This test asserts the live PG has all 4 expected enums:
      * run_status
      * asset_status
      * audit_action
      * exercise_status     (the one 0006 forgot)

    Run with:
        DIVIDE_TEST_LIVE_PG=1 pytest -m live_pg services/api/tests/test_live_pg.py

    The test reads the DB URL directly from the env var set by the
    conftest fixture (rather than importing the helper) so it cannot
    break the autouse ``_create_tables`` fixture for other tests in
    the suite.
    """
    import asyncio
    import os

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("DIVIDE_TEST_LIVE_PG_URL") or os.environ.get(
        "DIVIDE_TEST_LIVE_PG"
    )
    assert url and url != "1" and url != "true" and url != "yes", (
        "Set DIVIDE_TEST_LIVE_PG_URL (not just DIVIDE_TEST_LIVE_PG=1) "
        "to a full postgresql+asyncpg:// URL."
    )

    async def _check() -> list[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sa.text(
                        "SELECT t.typname FROM pg_type t "
                        "JOIN pg_namespace n ON n.oid = t.typnamespace "
                        "WHERE n.nspname='public' AND t.typtype='e' "
                        "ORDER BY t.typname"
                    )
                )
                return [r[0] for r in rows.fetchall()]
        finally:
            await engine.dispose()

    types = asyncio.run(_check())
    expected = {"run_status", "asset_status", "audit_action", "exercise_status"}
    missing = expected - set(types)
    assert not missing, (
        f"Postgres is missing enum types that models.py declares: "
        f"{sorted(missing)}. "
        f"Found types: {types}. "
        f"This is the Q4 regression: a migration declared the column as "
        f"VARCHAR but the model uses Enum(NAME, ...). Re-run "
        f"`alembic upgrade head` to apply the missing 0013 migration."
    )


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
