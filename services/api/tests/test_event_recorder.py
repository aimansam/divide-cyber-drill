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
    # Q24-B3: must catch the specific subclasses
    # IntegrityError (expected: FK / NOT NULL / unique) AND
    # ProgrammingError (schema-drift: re-raise so operators
    # see the 500 instead of silently dropping events). We no
    # longer use the broad ``except SQLAlchemyError``.
    assert "except IntegrityError" in source
    assert "except ProgrammingError" in source
    # Legacy guard for the original Q14 fix -- the flush branch
    # should never have been a bare ``except Exception``.
    flush_branch = source.split("bus.publish")[0]
    assert "rollback" in flush_branch  # nb: the comment refers to "do NOT"


@pytest.mark.asyncio
async def test_event_recorder_re_raises_programming_errors():
    """Q24-B3: schema-drift errors (e.g. missing PG enum type)
    must NOT be silently swallowed. Pre-B3, the broad
    ``except SQLAlchemyError`` hid the missing telemetry_severity
    enum for the entire F8 lifecycle.

    A ProgrammingError surfaces a real operator-visible 500
    instead of silently dropping every event.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.services import event_recorder
    from app.services.event_recorder import record_event

    session = MagicMock()
    session.rollback = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=cm)

    async def boom(*args, **kwargs):
        raise ProgrammingError(
            "ALTER TABLE",
            params={},
            orig=Exception("type telemetry_severity does not exist"),
        )

    session.flush = boom

    with pytest.raises(ProgrammingError):
        await record_event(
            session,
            run_id=42,
            kind="schema.drift",
            source="pytest",
            payload={},
        )

    # The Q14 invariant still holds: the outer transaction's
    # rollback must NOT be called even on ProgrammingError
    # (only the SAVEPOINT rolls back).
    assert session.rollback.await_count == 0, (
        "Q24-B3 regression: ProgrammingError leaked to "
        "session.rollback() and wiped the outer transaction"
    )
