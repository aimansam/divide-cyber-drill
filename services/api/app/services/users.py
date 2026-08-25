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
      * Email the reset link. The admin copies it from the admin
        UI and sends it via whatever channel exists (Slack,
        carrier pigeon). No SMTP integration. The ``forgot-password``
        endpoint deliberately returns 202 on unknown subs so the
        caller can't enumerate users.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHash,
    VerifyMismatchError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role
from app.db import models as db_models


def _as_utc(dt: datetime) -> datetime:
    """Normalize a DB-returned datetime to offset-aware UTC.

    SQLite stores datetimes as strings; SQLAlchemy returns them
    offset-naive. PostgreSQL returns them offset-aware. We compare
    against ``datetime.now(UTC)`` which is always offset-aware,
    so we need to coerce naive values into UTC before comparing.
    Real production (Postgres) is unaffected.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt

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


async def set_user_disabled(
    session: AsyncSession,
    *,
    sub: str,
    disabled: bool,
) -> db_models.User:
    """Flip a user's ``disabled`` flag.

    Used by the admin user-management UI (UserListCard's
    toggle-disabled button). Returns the refreshed user row
    after the flip. Raises:
      * ``UserNotFoundError`` if no user with that ``sub`` exists.
    """
    user = await get_by_sub(session, sub)
    if user is None:
        raise UserNotFoundError(f"user with sub {sub!r} not found")
    user.disabled = disabled
    await session.flush()
    await session.refresh(user)
    return user


class UserNotFoundError(Exception):
    """Raised by :func:`set_user_disabled` when the sub is unknown.

    The router turns this into a 404.
    """


# --- password reset (F-reset-ux) -------------------------------------------
#
# One-time password reset flow. Three primitives:
#
#   * :func:`issue_reset_token` -- write a fresh random token +
#     expiry to a user row. Returns ``None`` if the user doesn't
#     exist (the forgot-password router swallows that to prevent
#     enumeration).
#   * :func:`consume_reset_token` -- validate a token + sub pair
#     against a user row. If valid, clear the token (single-use),
#     return the user. If invalid (no token, expired, mismatched),
#     raise :class:`InvalidResetTokenError`. The router turns that
#     into a 401.
#   * :func:`set_password` -- replace a user's password hash. Used by
#     ``consume_reset_token`` and available for any admin path that
#     wants to change a password directly.
#
# Tokens are 32 bytes of ``secrets.token_urlsafe`` randomness (~43
# base64 chars). That's 256 bits of entropy, well above the "can't
# brute-force" threshold for any LAN deployment. We store the token
# verbatim because the reset endpoint has to do an equality lookup;
# hashing the token would add no security and would block the admin
# from copying the URL.

_RESET_TOKEN_TTL_S: int = 24 * 3600  # 24 hours


class InvalidResetTokenError(Exception):
    """Raised by :func:`consume_reset_token` on any failure.

    Covers: user not found, no token pending, token expired, token
    mismatch. The router returns a single generic 401 message so a
    caller can't tell which axis failed. (Enumeration of "does this
    user exist" via the reset endpoint is already prevented by
    :func:`issue_reset_token` returning ``None`` silently on unknown
    subs.)
    """


def _new_reset_token() -> str:
    """Cryptographically random URL-safe token, ~43 chars."""
    return secrets.token_urlsafe(32)


async def issue_reset_token(
    session: AsyncSession,
    *,
    sub: str,
) -> str | None:
    """Mint a fresh reset token for ``sub``.

    Returns the token string on success, ``None`` if no user with
    that sub exists (caller should swallow to prevent enumeration).
    Overwrites any previous token — a user can only have one active
    reset in flight at a time.

    The TTL is :data:`_RESET_TOKEN_TTL_S` (24h). The token column
    pair is updated atomically (``reset_token`` AND
    ``reset_token_expires_at`` in the same ``flush``). Callers
    should ``commit`` after this returns.
    """
    user = await get_by_sub(session, sub)
    if user is None:
        return None
    token = _new_reset_token()
    user.reset_token = token
    user.reset_token_expires_at = datetime.now(UTC) + timedelta(
        seconds=_RESET_TOKEN_TTL_S
    )
    await session.flush()
    return token


async def consume_reset_token(
    session: AsyncSession,
    *,
    sub: str,
    token: str,
) -> db_models.User:
    """Validate a (sub, token) pair and clear the token on success.

    Raises :class:`InvalidResetTokenError` on any failure. On
    success the token columns are cleared (single-use semantics)
    and the user row is returned so the caller can write the new
    password hash. The caller is responsible for committing.
    """
    user = await get_by_sub(session, sub)
    if user is None:
        raise InvalidResetTokenError("user not found")
    if not user.reset_token or not user.reset_token_expires_at:
        raise InvalidResetTokenError("no reset in flight")
    if user.reset_token != token:
        raise InvalidResetTokenError("token mismatch")
    if _as_utc(user.reset_token_expires_at) < datetime.now(UTC):
        # Don't bother clearing — the expiry already invalidates.
        raise InvalidResetTokenError("token expired")
    # Single-use: clear before returning.
    user.reset_token = None
    user.reset_token_expires_at = None
    await session.flush()
    return user


async def set_password(
    session: AsyncSession,
    *,
    user: db_models.User,
    new_password: str,
) -> None:
    """Replace ``user.password_hash`` with an argon2id hash of
    ``new_password``.

    Validation matches :func:`create_user`: non-empty, the rest is
    on the caller. Flushes; caller commits. Raises ``ValueError``
    on bad input (matches :func:`hash_password`).
    """
    user.password_hash = hash_password(new_password)
    await session.flush()


__all__ = [
    "DuplicateSubError",
    "InvalidResetTokenError",
    "UserNotFoundError",
    "UserStoreError",
    "authenticate",
    "consume_reset_token",
    "create_user",
    "get_by_sub",
    "hash_password",
    "issue_reset_token",
    "list_users",
    "set_password",
    "set_user_disabled",
    "touch_last_login",
    "verify_password",
]
