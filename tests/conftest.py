"""conftest for tests/.

The tests under this directory span smoke tests, doc-invariant tests,
and a few live-drill tests that need a real API. The session-scoped
``client`` fixture spins up an in-process FastAPI app via TestClient
so portal/mount assertions can hit ``/portal/``, ``/portal/app/`` without needing docker-compose up.
"""
from __future__ import annotations

import os

# Portal dir must be set BEFORE app modules import so the StaticFiles
# mount sees services/portal/. Matches services/api/tests/conftest.py.
os.environ.setdefault("DIVIDE_PORTAL_DIR", "services/portal")

import pytest
from fastapi.testclient import TestClient

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)
