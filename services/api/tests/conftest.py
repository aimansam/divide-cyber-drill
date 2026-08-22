"""Pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

# --- live PG mode ---------------------------------------------------------
#
# Setting DIVIDE_TEST_LIVE_PG to a non-empty value switches the test suite
# from SQLite to a real PostgreSQL. Useful for catching enum/JSONB/case
# bugs that SQLite is permissive about. Tests that should only run under
# live PG should be marked with ``@pytest.mark.live_pg``; they're skipped
# otherwise so the default `pytest` run stays SQLite-only and fast.
#
# The URL defaults to the docker-compose dev DB; override via env if needed.
LIVE_PG_URL_DEFAULT = "postgresql+asyncpg://divide:divide@localhost:5432/divide_test"


def _live_pg_url() -> str | None:
    val = os.environ.get("DIVIDE_TEST_LIVE_PG", "").strip()
    if not val:
        return None
    if val in ("1", "true", "yes"):
        return os.environ.get("DIVIDE_TEST_LIVE_PG_URL", LIVE_PG_URL_DEFAULT)
    return val


@pytest.fixture(scope="session", autouse=True)
def _env(monkeypatch_session):
    """Set sane defaults for tests."""
    monkeypatch_session.setenv("DIVIDE_ENV", "dev")
    monkeypatch_session.setenv("DIVIDE_LOG_LEVEL", "WARNING")
    if _live_pg_url():
        # Live PG mode — caller is responsible for pointing at a working DB.
        monkeypatch_session.setenv("DIVIDE_DB_URL", _live_pg_url())
    else:
        # Use SQLite for tests — no Postgres needed for unit tests.
        os.environ.setdefault("DIVIDE_DB_URL", "sqlite+aiosqlite:///./test.sqlite")
    yield


@pytest.fixture(scope="session")
def monkeypatch_session():
    from _pytest.monkeypatch import MonkeyPatch

    m = MonkeyPatch()
    yield m
    m.undo()


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Run all alembic migrations once per test session so router tests have
    tables. We use a single file-based SQLite and tear it down at the end.

    Why alembic over ``Base.metadata.create_all``?
    - Alembic is what runs in production.
    - Models drift from migrations all the time; this catches it.
    """
    import subprocess
    import sys

    live = _live_pg_url()

    if live:
        # Live PG mode — caller supplies the URL via DIVIDE_TEST_LIVE_PG.
        # We trust it and skip the alembic step (assume migrations are
        # already applied by the operator).
        os.environ["DIVIDE_DB_URL"] = live
        from app.services import db as db_module
        from app.db import session as session_module

        db_module._engine = None
        session_module._session_maker = None
        yield
        return

    db_path = Path(__file__).resolve().parents[1] / "_pytest_state" / "test.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    env = dict(os.environ)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    # Use the alembic binary against the same DB.
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(alembic_ini), "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd=alembic_ini.parent,
    )
    if r.returncode != 0:  # pragma: no cover - debug aid
        print("---STDOUT---")
        print(r.stdout)
        print("---STDERR---")
        print(r.stderr)
        raise RuntimeError("alembic upgrade head failed")

    # Point the running app at the same DB.
    os.environ["DIVIDE_DB_URL"] = f"sqlite+aiosqlite:///{db_path}"
    # Reset the cached engine / sessionmaker so tests pick up the new URL.
    from app.services import db as db_module

    db_module._engine = None
    from app.db import session as session_module

    session_module._session_maker = None

    yield

    try:
        db_path.unlink()
    except OSError:  # pragma: no cover
        pass


def pytest_collection_modifyitems(config, items):
    """Skip live_pg tests unless DIVIDE_TEST_LIVE_PG is set."""
    if _live_pg_url():
        return  # live PG requested — let the tests run
    skip_marker = pytest.mark.skip(reason="DIVIDE_TEST_LIVE_PG not set")
    for item in items:
        if "live_pg" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def client() -> TestClient:
    # Reset cached DB engine + sessionmaker so each test sees the
    # SQLite (or live PG) URL set by the db_setup fixture rather than
    # whatever URL a previous test left cached. Without this,
    # test_readyz_returns_503_when_db_unreachable poisons the engine
    # for all subsequent tests.
    from app.db import session as session_module
    from app.services import db as db_module
    from app.core.config import get_settings

    get_settings.cache_clear()
    db_module._engine = None
    session_module._session_maker = None

    from app.main import app

    return TestClient(app)
