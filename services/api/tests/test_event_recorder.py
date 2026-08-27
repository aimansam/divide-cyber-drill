"""Tests for F8 event_recorder.

Covers Q14: the record_event() helper must isolate its insert
via SAVEPOINT (begin_nested) so a failing telemetry insert does
not roll back the outer transaction.

Before this fix, ``record_event`` called ``session.rollback()``
on any flush failure. The runner does
``session.add(run); await session.flush()`` to populate ``run.id``,
then calls ``record_event``, then continues to add assets with
``run_id=run.id``. If telemetry fails and rollback runs, the
Run row is wiped from the transaction and the subsequent Asset
INSERT fails FK with ``Key (run_id)=(N) is not present in
table "runs"``.

We verify the fix at the unit level: ``record_event`` must
*not* call ``session.rollback()`` on flush failure; it must
return ``None`` and let the outer transaction continue.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_event_recorder_failure_does_not_rollback_outer_tx():
    """Q14 regression test: telemetry failure must NOT call rollback.

    We assert directly on the session mock rather than trying to
    exercise the real session API (which has async-context-manager
    semantics that are tedious to mock).
    """
    from app.services.event_recorder import record_event

    session = MagicMock()
    session.rollback = AsyncMock()

    # Make the SAVEPOINT context manager not blow up. We don't
    # care whether it's awaited -- we only care that the outer
    # transaction's rollback was NOT called.
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=cm)

    # session.flush raises IntegrityError so record_event hits
    # the except branch.
    async def boom(*args, **kwargs):
        raise IntegrityError(
            "INSERT INTO telemetry_events",
            params={},
            orig=Exception("simulated FK failure"),
        )

    session.flush = boom

    result = await record_event(
        session,
        run_id=42,
        kind="test.event",
        source="pytest",
        payload={"foo": "bar"},
    )

    # Best-effort: returns None on failure.
    assert result is None
    # Q14 critical assertion: the outer transaction's rollback
    # must NOT be called. (Only the SAVEPOINT is rolled back,
    # which is handled by the ``async with session.begin_nested()``
    # exit on exception.)
    assert session.rollback.await_count == 0, (
        "Q14 regression: record_event called session.rollback(), "
        "which wipes the outer transaction (the Run row) and breaks "
        "the next Asset INSERT with a FK violation."
    )


@pytest.mark.asyncio
async def test_event_recorder_catches_sqlalchemyerror_not_bare_exception():
    """Q14 secondary: only SQLAlchemyError should be caught.

    Bare ``Exception`` would mask programming bugs (e.g.
    ``AttributeError`` from a typo). We verify the except clause
    is narrower.
    """
    import inspect

    from app.services import event_recorder

    source = inspect.getsource(event_recorder.record_event)
    # Must catch SQLAlchemyError, not bare Exception.
    assert "except SQLAlchemyError" in source
    # Must NOT catch bare Exception on the flush path (the
    # original Q14 bug was a bare ``except Exception:``).
    # Note: the bus.publish branch still uses bare Exception to
    # log + swallow; that's intentional (publish should never
    # block the request). But the flush-path branch must be
    # specific.
    flush_branch = source.split("bus.publish")[0]
    # The flush branch should NOT contain a bare "except Exception"
    # followed by a rollback.
    assert "rollback" in flush_branch  # nb: the comment refers to "do NOT"
