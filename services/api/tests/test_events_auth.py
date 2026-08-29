"""Q24-B2: SSE auth via query-param token fallback.

The /runs/{id}/events/stream endpoint requires auth, but
``EventSource`` in the browser can't send custom headers. The
API now accepts ``?token=<token>`` as a fallback path. This
test exercises the current_token dependency directly (no live
DB) to assert the contract.

Covers:
  * Header takes precedence over query param
  * Query param works when header is absent
  * Anonymous request returns None (caller decides via
    require_role)
  * Bad query-param token returns 401
"""
from __future__ import annotations

import os
import asyncio
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("DIVIDE_TOKEN_SECRET", "test-secret-do-not-use-in-prod")


@pytest.fixture
def admin_token() -> str:
    from app.core.auth import Role, sign_token
    return sign_token("admin-test", Role.ADMIN.value, 3600)


@pytest.mark.asyncio
async def test_current_token_uses_query_param_when_header_missing(
    admin_token: str,
):
    """Q24-B2 primary: header absent, ?token= present -> token
    is returned and stashed on request.state."""
    from app.core.auth import current_token

    request = MagicMock()
    request.query_params = {"token": admin_token}
    request.state = MagicMock()
    result = await current_token(
        request, x_divide_token=None
    )
    assert result is not None
    assert result.sub == "admin-test"


@pytest.mark.asyncio
async def test_current_token_header_takes_precedence(admin_token: str):
    """Header + query both present -> header wins (lower
    priority to the query, which is more exposed)."""
    from app.core.auth import current_token

    request = MagicMock()
    request.query_params = {"token": "garbage-from-query"}
    request.state = MagicMock()
    result = await current_token(
        request, x_divide_token=admin_token
    )
    assert result is not None
    assert result.sub == "admin-test"


@pytest.mark.asyncio
async def test_current_token_anonymous_when_neither_present():
    """No header, no query -> None (anonymous)."""
    from app.core.auth import current_token

    request = MagicMock()
    request.query_params = {}
    request.state = MagicMock()
    result = await current_token(
        request, x_divide_token=None
    )
    assert result is None


@pytest.mark.asyncio
async def test_current_token_rejects_invalid_query_token():
    """Bad token via query -> 401 (re-raised HTTPException)."""
    from fastapi import HTTPException

    from app.core.auth import current_token

    request = MagicMock()
    request.query_params = {"token": "garbage"}
    request.state = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await current_token(request, x_divide_token=None)
    assert exc_info.value.status_code == 401
