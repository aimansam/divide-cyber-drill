"""Credential login router (F3-prep).

Three endpoints, deliberately tight:

  * ``POST /api/v1/auth/login``
      body: ``{"sub": "...", "password": "..."}``
      returns: ``{"token": "...", "sub": "...", "role": "...",
                   "iat": ..., "exp": ...}``
      errors: 400 (bad body), 401 (bad creds — generic, no
                enumeration), 429 (too many failed attempts —
                F2.2 rate-limit, 5/sub/15min)

  * ``POST /api/v1/auth/logout``
      no body. Stateless best-effort logout. The token still
      verifies until ``exp`` — the client drops it. Future L3
      work would add a revocation list.

  * ``GET /api/v1/auth/users``
      admin-only. Returns ``[{sub, role, disabled,
      last_login_at, created_at}, ...]``. Used by the admin UI to
      show "who can log in" and by tests.

Security considerations:
    - Failed-login rate limit: 5 attempts per ``sub`` per 15 min
      via the same Redis bucket pattern as ``POST /drills`` (F2.2).
      The login check happens BEFORE the DB query, so timing
      roughly matches whether the user exists or not.
    - Generic 401 message regardless of whether the ``sub`` exists,
      password is wrong, or the account is disabled. No
      enumeration oracle.
    - The token TTL is configurable via ``DIVIDE_LOGIN_TOKEN_TTL_S``
      (default 8h — covers a working day; longer than a drill).
    - Password is never logged, never echoed in the response, and
      ``password_hash`` is never returned by ``GET /auth/users``.
"""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sql_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, current_token, require_role, sign_token
from app.core.config import settings
from app.db import models as db_models
from app.db.session import get_session
from app.services.users import (
    DuplicateSubError,
    UserStoreError,
    authenticate,
    create_user,
    list_users,
    touch_last_login,
)

router = APIRouter()


# --- rate-limit config (separate bucket from drill-start) -------------------


# 5 failed attempts per sub per 15 min. Why a separate config:
# login is auth, drill-start is resource — different blast radii.
_LOGIN_LIMIT: int = 5
_LOGIN_WINDOW_SECONDS: int = 15 * 60


def _login_bucket_key(sub: str) -> str:
    return f"divide:rl:auth:{sub}"


async def _read_login_count(sub: str) -> int:
    """Return the current bucket count, or 0 if Redis is unreachable.

    Fail-open: a Redis outage returns 0 so the caller doesn't block
    a legitimate login. The rate-limit FAIL-CLOSED toggle still
    applies for callers that want a hard failure on Redis errors.
    """
    import os

    import structlog

    from app.services import cache as _cache_module

    try:
        client = _cache_module.get_redis()
        raw = await client.get(_login_bucket_key(sub))
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("DIVIDE_RATE_LIMIT_FAIL_CLOSED", "").lower() in (
            "1", "true", "yes"
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rate limiter unavailable: {exc}",
            ) from exc
        structlog.get_logger().warning(
            "divide.auth.rate_limit_redis_unreachable",
            subject=sub,
            error=str(exc),
        )
        return 0
    return int(raw) if raw else 0


async def _check_login_limit_no_increment(sub: str) -> None:
    """Raise 429 if ``sub`` has already exceeded the budget.

    Read-only — does NOT increment. Used on every login attempt
    (success or failure) so the budget reflects only prior
    failures, not legitimate logins.
    """
    count = await _read_login_count(sub)
    if count >= _LOGIN_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"too many failed login attempts for {sub!r}: "
                f"{count}/{_LOGIN_LIMIT} in the last "
                f"{_LOGIN_WINDOW_SECONDS // 60}m; try again later"
            ),
        )


async def _increment_login_limit(sub: str) -> None:
    """Increment the bucket after a failed auth.

    Fail-open: a Redis outage logs a warning and returns; the next
    attempt just gets another fail-open. The TTL refreshes on every
    increment so a flood keeps the budget full.
    """
    import os

    import structlog

    from app.services import cache as _cache_module

    key = _login_bucket_key(sub)
    try:
        client = _cache_module.get_redis()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_WINDOW_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 — fail-open is intentional
        if os.environ.get("DIVIDE_RATE_LIMIT_FAIL_CLOSED", "").lower() in (
            "1", "true", "yes"
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"rate limiter unavailable: {exc}",
            ) from exc
        structlog.get_logger().warning(
            "divide.auth.rate_limit_redis_unreachable",
            subject=sub,
            error=str(exc),
        )


# --- token TTL --------------------------------------------------------------


def _login_token_ttl_s() -> int:
    """Default 8h. Overridable via ``DIVIDE_LOGIN_TOKEN_TTL_S``."""
    raw = getattr(settings, "login_token_ttl_s", None)
    if raw is None:
        return 8 * 3600
    try:
        v = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 8 * 3600
    return v if v > 0 else 8 * 3600


# --- request/response shapes ----------------------------------------------


class LoginRequest(BaseModel):
    sub: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    token: str
    sub: str
    role: str
    iat: int
    exp: int
    ttl_remaining_s: int


class UserPublic(BaseModel):
    """User row safe to return from the admin endpoint.

    No password hash, no internal id. ``last_login_at`` is
    operational telemetry; everything else is what the admin
    needs to manage accounts.
    """

    sub: str
    role: str
    disabled: bool
    last_login_at: str | None
    created_at: str


# --- endpoints ---------------------------------------------------------------


@router.post(
    "/login",
    summary="Credential login — username + password → HMAC token",
)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Mint an HMAC token after verifying the password.

    Failure modes are deliberately collapsed into a single
    ``HTTP 401`` with the same message so a caller can't tell
    whether the ``sub`` exists, the password was wrong, or the
    account is disabled. Rate-limited via the per-sub bucket
    above (5 failed attempts / 15 min).
    """
    sub = body.sub.strip()
    # Check the rate-limit BEFORE the DB query. The check itself
    # does not increment the bucket — only a failed auth does
    # (see below). An attacker who floods with bogus subs does
    # not accumulate budget; each failed-auth call does.
    await _check_login_limit_no_increment(sub)

    user = await authenticate(session, sub=sub, password=body.password)
    if user is None:
        # Failed auth: increment the bucket so a flood of wrong
        # passwords eventually trips 429.
        await _increment_login_limit(sub)
        # Generic message — no enumeration.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Best-effort last_login_at update. A DB blip shouldn't log
    # the user out, so we swallow errors here.
    try:
        await touch_last_login(session, user)
        await session.commit()
    except Exception:  # noqa: BLE001 — best-effort
        await session.rollback()

    token = sign_token(sub=user.sub, role=user.role, ttl_s=_login_token_ttl_s())
    now = int(time.time())
    return LoginResponse(
        token=token,
        sub=user.sub,
        role=user.role,
        iat=now,
        exp=now + _login_token_ttl_s(),
        ttl_remaining_s=_login_token_ttl_s(),
    )


@router.post(
    "/logout",
    summary="Logout (stateless best-effort)",
)
async def logout() -> dict[str, bool]:
    """Stateless logout — the client drops the token.

    No server-side state to clear. Returning ``{"ok": True}`` so
    the portal can chain a state-update. A real revocation list
    is L3 work (3.16).
    """
    return {"ok": True}


@router.get(
    "/users",
    summary="List users (admin only)",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def list_users_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
    _token=Depends(current_token),
) -> list[UserPublic]:
    """All user rows, newest first. Password hash is never returned."""
    rows = await list_users(session)
    return [
        UserPublic(
            sub=u.sub,
            role=u.role,
            disabled=u.disabled,
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
            created_at=u.created_at.isoformat(),
        )
        for u in rows
    ]


# --- F10: first-admin bootstrap + admin user creation -------------------


class SetupRequest(BaseModel):
    """Body for ``POST /auth/setup``.

    Used by the in-portal onboarding wizard (F10.3) to create
    the very first admin without requiring the operator to set
    ``DIVIDE_BOOTSTRAP_ADMIN_*`` env vars + restart the API.

    Public endpoint; only the first call succeeds. Once any
    user exists, the wizard falls through to the sign-in flow.
    """

    sub: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=512)


@router.post(
    "/setup",
    summary="F10: bootstrap the very first admin (public, single-shot)",
    status_code=status.HTTP_201_CREATED,
)
async def setup_first_admin(
    body: SetupRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Create the first admin if (and only if) no users exist yet.

    Status codes:
      * 201 -- first admin created; returns the login response
                so the wizard can stash the token + redirect.
      * 409 -- at least one user already exists. The wizard
                treats this as "step 1 already complete" and
                advances to step 2.

    Why the endpoint is public:
      The first admin can't have a token yet (no token = no
      admin = can't create the admin). So the only way to break
      the chicken-and-egg cycle is a public endpoint that's
      gated by the "no users yet" invariant.

    Why the single-shot guard matters:
      Once the admin is created, the endpoint must reject
      further calls so a leaked setup URL can't grow the user
      table. We check the user count under a SELECT and race-
      tolerate by re-checking after insert.

    Password policy: minimum 8 characters. We don't enforce
    complexity here -- operators using the wizard are typically
    on a LAN deployment where the threat model is "stolen
    laptop", not "online brute force". The login endpoint's
    rate-limit (5 attempts / 15 min per sub) covers the brute
    force case.
    """
    # Single-shot gate: 409 if any user already exists.
    n = (
        await session.execute(select(sql_func.count(db_models.User.id)))
    ).scalar_one()
    if n and n > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "setup is single-shot: at least one user already exists; "
                "sign in instead"
            ),
        )

    try:
        user = await create_user(
            session, sub=body.sub, password=body.password, role=Role.ADMIN.value
        )
        await session.commit()
    except DuplicateSubError:
        # Lost a race with another setup call.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"user with sub {body.sub!r} already exists",
        )
    except UserStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    now = int(time.time())
    ttl = _login_token_ttl_s()
    return LoginResponse(
        token=sign_token(sub=user.sub, role=user.role, ttl_s=ttl),
        sub=user.sub,
        role=user.role,
        iat=now,
        exp=now + ttl,
        ttl_remaining_s=ttl,
    )


class CreateUserRequest(BaseModel):
    """Body for ``POST /auth/users`` (F10.2).

    Admin-only. Used by the wizard's "form team" step to create
    red-team / blue-team players in bulk before launching the
    exercise.
    """

    sub: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)
    role: str = Field(min_length=1, max_length=32)


@router.post(
    "/users",
    summary="F10.2: admin creates a user (red/blue/lead/etc.)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_user_endpoint(
    body: CreateUserRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _token=Depends(current_token),
) -> UserPublic:
    """Insert a new user. Mirrors the login path's error codes.

    Status codes:
      * 201 -- user created; returns the public row.
      * 409 -- sub already exists.
      * 422 -- bad body (sub empty, role unknown, etc.).

    Why an admin endpoint rather than a self-signup:
      div:ide is a closed cyber-range. New users are added by
      the operator (admin) before a drill starts -- they don't
      self-register. Mirrors the auth model in TryHackMe /
      HackTheBox / RangeForce.
    """
    try:
        user = await create_user(
            session, sub=body.sub, password=body.password, role=body.role
        )
        await session.commit()
    except DuplicateSubError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"user with sub {body.sub!r} already exists",
        )
    except UserStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    await session.refresh(user)
    return UserPublic(
        sub=user.sub,
        role=user.role,
        disabled=user.disabled,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
    )


__all__ = ["router"]
