"""Pytest fixtures."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base


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
    """Create the schema once per test session so router tests have tables."""
    test_db = os.environ.get("DIVIDE_DB_URL", "sqlite+aiosqlite:///./test.sqlite")
    # Sync driver for table creation: drop the +aiosqlite suffix.
    from sqlalchemy import create_engine as _create_sync

    sync_url = test_db.replace("+aiosqlite", "")
    sync_eng = _create_sync(sync_url)
    # Import models so they register on Base.metadata before create_all.
    from app.db import models  # noqa: F401
    Base.metadata.create_all(sync_eng)
    sync_eng.dispose()
    yield


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)
