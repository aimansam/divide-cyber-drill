"""User store + password hashing for F3-prep credential login.

Why this exists alongside ``tools/issue_token.py``:

      * The paste-your-token flow still works for SSH operators and
        emergencies (kept on purpose — admin-gated bootstrap path).
      * The portal's sign-in screen (``SignInCard``) needs a real
        username + password POST so non-SSH operators can demo
        without keeping a copy of ``tools/issue_token.py`` handy.
      * ``tools/issue_token.py`` is the developer ergonomics, this
        module is the production login flow. Both mint the same
        HMAC-SHA256 token shape; the difference is how the caller
        proves their identity to get one.

Password hashing choice: argon2id via ``argon2-cffi``. Rationale:

      * argon2id won the Password Hashing Competition (2015) and is
        the OWASP-recommended default as of the time of writing.
      * No memory-vs-CPU trade-off to tune by hand; the library's
        default parameters (``time_cost=2, memory_cost=64 MiB,
        parallelism=4``) are sane for both dev and small LAN prod.
      * bcrypt would be a defensible alternative; we picked argon2id
        because it has a clearer forward-migration story (parameter
        bump via ``PasswordHasher``'s ``check_needs_rehash``).

What this module does NOT do:

      * Issue tokens. That lives in :mod:`app.core.auth.sign_token`.
        Login flow calls it after ``authenticate`` succeeds.
      * Rate-limit failed attempts. The login router does that via
        :mod:`app.services.rate_limit` (F2.2).
      * Disable account permanently. ``User.disabled`` is the kill
        switch; this module just respects it.
      * Self-signup. Admin-only creation.
"""
from __future__ import annotations

from datetime import UTC

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHash,
    VerifyMismatchError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role
from app.db import models as db_models

# Singleton hasher; library is internally thread-safe.
# = argon2-cffi defaults: time_cost=2, memory_cost=64 MiB, parallelism=4,
# hash_len=32, salt_len=16, type=ID. Tuned for a dev box on a LAN.
# If a future benchmark says the LAN API is CPU-bound, bump time_cost.
_HASHER = PasswordHasher()


# --- hashing ---------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an argon2id PHC string for ``password``.

    The output includes a random salt and the chosen parameters
    (``$argon2id$v=19$m=...,t=...,p=...$salt$hash``). Two callers
    passing the same password get different strings.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time-ish check; returns False on any mismatch.

    Catches:

      * bad PHC format (caller stored a non-argon2id string)
      * wrong password
      * mismatched hash type (e.g. bcrypt string in an argon2 column)

    Returns ``True`` iff the password matches. Never raises — the
    router turns a False into 401 with a generic "invalid credentials"
    message so we don't leak which axis failed.
    """
    if not password_hash or not isinstance(password_hash, str):
        return False
    if not password or not isinstance(password, str):
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


# --- store ------------------------------------------------------------------


class UserStoreError(Exception):
    """Raised by :func:`create_user` on validation failures.

    The router turns ``DuplicateSubError`` into 409; other messages
    bubble up as 400.
    """


class DuplicateSubError(UserStoreError):
    """``sub`` already exists in the table."""


async def create_user(
    session: AsyncSession,
    *,
    sub: str,
    password: str,
    role: str,
) -> db_models.User:
    """Insert a new user row.

    Validation:

      * ``sub`` is trimmed; empty -> ``UserStoreError``.
      * ``password`` is non-empty (length is policy, not ours).
      * ``role`` must be a member of :class:`app.core.auth.Role`.
        Unknown role strings are rejected so a typo can't mint a
        user with ``role="admine"`` (silent privilege escalation).

    Returns the persisted :class:`User` (id, created_at populated).
    Raises :class:`DuplicateSubError` on the unique constraint.
    """
    if not sub or not isinstance(sub, str):
        raise UserStoreError("sub must be a non-empty string")
    sub = sub.strip()
    if not sub:
        raise UserStoreError("sub must be a non-empty string")
    if not password or not isinstance(password, str):
        raise UserStoreError("password must be a non-empty string")
    if not role or not isinstance(role, str):
        raise UserStoreError("role must be a non-empty string")
    valid_roles = {r.value for r in Role}
    if role not in valid_roles:
        raise UserStoreError(
            f"role {role!r} not in {sorted(valid_roles)}; "
            f"must be one of: {', '.join(sorted(valid_roles))}"
        )

    user = db_models.User(
        sub=sub,
        password_hash=hash_password(password),
        role=role,
        disabled=False,
    )
    session.add(user)
    try:
        await session.flush()
    except Exception as exc:  # IntegrityError on duplicate sub
        await session.rollback()
        msg = str(exc).lower()
        if "uq_users_sub" in msg or "unique" in msg or "duplicate" in msg:
            raise DuplicateSubError(f"user with sub {sub!r} already exists") from exc
        raise
    await session.refresh(user)
    return user


async def authenticate(
    session: AsyncSession,
    *,
    sub: str,
    password: str,
) -> db_models.User | None:
    """Look up the user by ``sub`` and verify the password.

    Returns ``None`` on any failure (unknown sub, wrong password,
    disabled account). Does NOT raise — the router turns ``None``
    into a 401 with a single generic message. Returning ``None``
    on disabled too is intentional: from the outside, "disabled"
    and "unknown" must look identical so an admin can freeze a
    malicious account without confirming whether the name exists.

    The DB lookup is by primary key (sub is unique-indexed), so the
    cost is one index seek even with millions of users.
    """
    if not sub or not password:
        return None
    sub = sub.strip()
    if not sub:
        return None
    stmt = select(db_models.User).where(db_models.User.sub == sub)
    user: db_models.User | None = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        return None
    if user.disabled:
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


async def list_users(session: AsyncSession) -> list[db_models.User]:
    """All users, newest first. Admin-only at the router."""
    stmt = select(db_models.User).order_by(db_models.User.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_by_sub(session: AsyncSession, sub: str) -> db_models.User | None:
    """Single user lookup. Used by bootstrap and tests."""
    stmt = select(db_models.User).where(db_models.User.sub == sub)
    return (await session.execute(stmt)).scalar_one_or_none()


async def touch_last_login(session: AsyncSession, user: db_models.User) -> None:
    """Best-effort write of ``last_login_at = now()``.

    Called by the login router after a successful auth. Failures
    are swallowed by the caller (the user is already logged in;
    failing here would log them out, which is the wrong direction).
    """
    from datetime import datetime

    user.last_login_at = datetime.now(UTC)
    await session.flush()


__all__ = [
    "DuplicateSubError",
    "UserStoreError",
    "authenticate",
    "create_user",
    "get_by_sub",
    "hash_password",
    "list_users",
    "touch_last_login",
    "verify_password",
]
