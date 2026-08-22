"""Pytest fixtures."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture(scope="session", autouse=True)
def _env(monkeypatch_session):
    """Set sane defaults for tests."""
    monkeypatch_session.setenv("DIVIDE_ENV", "dev")
    monkeypatch_session.setenv("DIVIDE_LOG_LEVEL", "WARNING")
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


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)
