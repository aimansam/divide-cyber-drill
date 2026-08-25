"""Credential login router (F3-prep + F-reset-ux).

Three primary endpoints, deliberately tight:

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

Password-reset flow (F-reset-ux, added 2026-08):

  * ``POST /api/v1/auth/forgot-password``
      body: ``{"sub": "..."}``
      returns: 202 always (no enumeration). Mints a one-time
      reset token if the user exists.
  * ``POST /api/v1/auth/reset-password``
      body: ``{"sub": "...", "token": "...", "new_password": "..."}``
      returns: 204 on success, 401 on bad token (generic).
  * ``POST /api/v1/auth/users/{sub}/issue-reset``
      admin-only. Returns ``{"reset_token": "...", "magic_link":
      "..."}``. The admin copies the magic link and sends it to
      the locked-out user via whatever channel exists (Slack,
      carrier pigeon). No SMTP integration.

The reset-link format is ``<portal-origin>/#/?sub=<sub>&token=<token>``.
The portal renders a ResetPasswordCard when the URL hash includes
both ``sub`` and ``token`` query params. After the user submits a
new password, the portal drops the hash and lands on the sign-in
form.

Security considerations:
    - Failed-login rate limit: 5 attempts per ``sub`` per 15 min
      via the same Redis bucket pattern as ``POST /drills`` (F2.2).
      The login check happens BEFORE the DB query, so timing
      roughly matches whether the user exists or not.
    - Generic 401 message regardless of whether the ``sub`` exists,
      password is wrong, or the account is disabled. No
      enumeration oracle.
    - ``forgot-password`` returns 202 unconditionally -- the
      admin endpoint is the only path that actually surfaces the
      token; the public endpoint exists for symmetry with future
      "send me an email" workflows and to give the UI a place to
      show "check your admin".
    - Reset tokens are 32 bytes of ``secrets.token_urlsafe``
      randomness (~43 base64 chars). 24h TTL. Single-use: cleared
      on a successful ``POST /reset-password``.
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
    InvalidResetTokenError,
    UserNotFoundError,
    UserStoreError,
    authenticate,
    consume_reset_token,
    create_user,
    get_by_sub,
    issue_reset_token,
    list_users,
    set_password,
    set_user_disabled,
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


@router.get(
    "/setup",
    summary="Probe whether first-admin setup is needed (public)",
    status_code=status.HTTP_200_OK,
)
async def setup_probe(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Return ``{"needs_setup": true}`` when no users exist yet, otherwise
    ``{"needs_setup": false}``.

    This endpoint is intentionally public (no token required). It lets the
    portal decide on first paint whether to show the sign-in form (returning
    deployment) or the onboarding wizard (empty deployment).

    The only information leaked is "has any user ever been created?" — the
    same binary fact a caller learns from getting a 409 on
    ``POST /auth/setup``. No enumeration risk.
    """
    count: int = (
        await session.execute(select(sql_func.count()).select_from(db_models.User))
    ).scalar_one()
    return {"needs_setup": count == 0}


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


@router.post(
    "/users/{sub}/toggle-disabled",
    summary="F9.4: flip a user's disabled flag (admin only)",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def toggle_disabled_endpoint(
    sub: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _token=Depends(current_token),
) -> UserPublic:
    """Toggle the ``disabled`` flag on a user row.

    Backs the UserListCard's toggle button in the portal. The
    endpoint reads the current value and flips it -- the
    portal doesn't need to know the current state.

    Status codes:
      * 200 -- toggled; returns the refreshed row.
      * 404 -- no user with that ``sub``.
      * 401/403 -- admin gate (handled by require_role).

    Note: the endpoint is a true toggle (read + flip), not a
    set. This is intentional -- the portal's button is a
    switch-style toggle, not a "set disabled = true" form.
    Set semantics can be added later if the admin UI grows
    checkbox-style controls.
    """
    from app.services.users import (
        UserNotFoundError,
        set_user_disabled,
    )

    current = await get_by_sub(session, sub)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user with sub {sub!r} not found",
        )

    try:
        user = await set_user_disabled(
            session, sub=sub, disabled=not current.disabled
        )
        await session.commit()
    except UserNotFoundError:
        # Lost a race with another delete.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user with sub {sub!r} not found",
        )

    return UserPublic(
        sub=user.sub,
        role=user.role,
        disabled=user.disabled,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Password reset (F-reset-ux)
# ---------------------------------------------------------------------------
#
# Three endpoints. The flow:
#
#   1. User clicks "Forgot password" on the sign-in form.
#   2. Portal POSTs /auth/forgot-password. The endpoint silently
#      mints a token if the user exists; returns 202 either way.
#   3. An admin (separately, on the Admin tab) clicks "Reset link"
#      for the user, which calls /auth/users/{sub}/issue-reset.
#      The response contains a magic_link the admin copies and
#      sends to the user.
#   4. User clicks the link, the portal renders ResetPasswordCard
#      (parsed from the URL hash). They POST /auth/reset-password
#      with sub + token + new_password. Single-use: the token is
#      cleared atomically with the password write.


class ForgotPasswordRequest(BaseModel):
    """Body for ``POST /auth/forgot-password``."""

    sub: str = Field(min_length=1, max_length=64)


class ForgotPasswordResponse(BaseModel):
    """Always returns the same shape -- we never leak whether the
    user exists."""

    ok: bool = True
    message: str = (
        "If the account exists, a reset link has been sent to your "
        "admin. Ask them to check the Admin tab."
    )


@router.post(
    "/forgot-password",
    summary="Request a password reset (public; no enumeration)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    body: ForgotPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ForgotPasswordResponse:
    """Mint a reset token if the user exists; return 202 either way.

    This endpoint does NOT send anything (no SMTP). The token is
    stored on the user row; the admin endpoint below is what
    actually surfaces it. The point of having a public
    ``forgot-password`` at all is to give the sign-in card's "I
    forgot my password" button something to POST to that returns
    a consistent response shape.

    Status codes:
      * 202 -- always (no enumeration).
      * 422 -- bad body (sub empty or too long).
    """
    sub = body.sub.strip()
    if sub:
        # Best-effort. If the user doesn't exist, ``issue_reset_token``
        # returns None and we silently swallow it.
        await issue_reset_token(session, sub=sub)
        await session.commit()
    return ForgotPasswordResponse()


class ResetPasswordRequest(BaseModel):
    """Body for ``POST /auth/reset-password``."""

    sub: str = Field(min_length=1, max_length=64)
    token: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=512)


@router.post(
    "/reset-password",
    summary="Consume a reset token and set a new password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_password(
    body: ResetPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Validate ``sub`` + ``token``; on success, write the new
    password hash and clear the token.

    Status codes:
      * 204 -- password changed. The user can now sign in.
      * 401 -- any failure (no token, expired, mismatched, user
                gone). Single generic message; no enumeration.
      * 422 -- bad body (empty sub, weak password, etc.).
    """
    sub = body.sub.strip()
    try:
        user = await consume_reset_token(
            session, sub=sub, token=body.token
        )
        await set_password(session, user=user, new_password=body.new_password)
        await session.commit()
    except InvalidResetTokenError:
        # Generic message; the four failure modes collapse into one.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired reset token",
        )
    except ValueError as exc:
        # ``hash_password`` rejects empty / non-string passwords;
        # pydantic should catch that before we get here, but be
        # defensive.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


class IssueResetLinkResponse(BaseModel):
    """Body for ``POST /auth/users/{sub}/issue-reset`` (admin only).

    The ``reset_token`` is the raw token (in case the admin
    wants to construct their own link); ``magic_link`` is a
    fully-formed URL the admin can paste into Slack / email /
    whatever.

    Note: the token is sensitive. The portal's UserListCard
    immediately copies it to clipboard and never persists it.
    """

    sub: str
    reset_token: str
    magic_link: str
    expires_at: str  # ISO 8601, UTC


@router.post(
    "/users/{sub}/issue-reset",
    summary="Admin: mint a reset token + magic link for a user",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def issue_reset_link(
    sub: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _token=Depends(current_token),
) -> IssueResetLinkResponse:
    """Mint a fresh reset token and return both the raw token and
    a fully-formed ``/#/?sub=&token=`` URL the admin can send to
    the user.

    Overwrites any previous in-flight reset. The portal renders
    ResetPasswordCard when the URL hash contains both query params.

    Status codes:
      * 200 -- token minted.
      * 404 -- no user with that sub.
      * 401/403 -- admin gate.
    """
    user = await get_by_sub(session, sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user with sub {sub!r} not found",
        )

    token = await issue_reset_token(session, sub=sub)
    if token is None:  # pragma: no cover -- guarded above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"user with sub {sub!r} not found",
        )
    await session.commit()
    await session.refresh(user)
    assert user.reset_token_expires_at is not None

    # Relative link: keeps the link valid regardless of how the
    # portal is hosted (docker-compose shares an origin with the
    # API; reverse-proxied deployments may need to edit the
    # hostname after pasting).
    magic_link = f"/portal/app/#/?sub={user.sub}&token={token}"

    return IssueResetLinkResponse(
        sub=user.sub,
        reset_token=token,
        magic_link=magic_link,
        expires_at=user.reset_token_expires_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# VPN config download
# ---------------------------------------------------------------------------


@router.get(
    "/vpn-config",
    summary="Download your WireGuard VPN config (authenticated users only)",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.RED, Role.BLUE, Role.OBSERVER,
    ))],
)
async def get_vpn_config(
    session: Annotated[AsyncSession, Depends(get_session)],
    token=Depends(current_token),
) -> dict:
    """Return a WireGuard client .conf for the authenticated user.

    On first call, a stable peer_id (UUID) is assigned to the user and
    persisted. On subsequent calls the same peer_id is reused, so the
    keypair and IP are stable across logins.

    The response body contains:
      ``config``    — the full .conf text (save as divide.conf)
      ``filename``  — suggested filename (``divide-<sub>.conf``)
      ``client_ip`` — the VPN IP assigned to this peer
      ``server_ip`` — the server's VPN IP (for reference)
      ``allowed_ips`` — the CIDRs routed over VPN

    Status codes:
      * 200 — config returned.
      * 401 — no/invalid token.
      * 503 — wg-easy not reachable (server_pubkey placeholder used).
    """
    from app.services.vpn import (
        assign_peer_id,
        build_client_config,
        client_ip,
        server_ip,
        peer_public_key,
    )
    from app.core.config import settings

    sub = token.sub

    # Load the user row (needed to get/set wg_peer_id).
    user = await get_by_sub(session, sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found",
        )

    # Assign a peer_id if this is the first VPN config request.
    if not user.wg_peer_id:
        user.wg_peer_id = assign_peer_id()
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Determine peer_index: count all users with a wg_peer_id < this one
    # (lexicographic on UUID, stable for ordering purposes).
    from sqlalchemy import func as sql_func, select as sql_select
    from app.db import models as db_models

    count_row = await session.execute(
        sql_select(sql_func.count()).select_from(db_models.User).where(
            db_models.User.wg_peer_id < user.wg_peer_id,
            db_models.User.wg_peer_id.isnot(None),
        )
    )
    peer_index = count_row.scalar_one() + 1  # 1-based; server is 0

    # Fetch server public key from wg-easy API (best-effort).
    server_pubkey = await _fetch_wg_server_pubkey()

    conf = build_client_config(
        peer_id=user.wg_peer_id,
        peer_index=peer_index,
        server_pubkey=server_pubkey,
    )

    return {
        "config": conf,
        "filename": f"divide-{sub}.conf",
        "client_ip": client_ip(peer_index),
        "server_ip": server_ip(),
        "allowed_ips": settings.wg_allowed_ips,
        "server_pubkey": server_pubkey,
    }


async def _fetch_wg_server_pubkey() -> str:
    """Fetch the WireGuard server public key from wg-easy.

    wg-easy exposes GET http://wg-easy:51821/api/wireguard/client
    (no auth for the public key endpoint in wg-easy v7+).
    Falls back to a placeholder if unreachable.
    """
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://wg-easy:51821/api/wireguard/server/key")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("publicKey", "") or data.get("key", "")
    except Exception:  # noqa: BLE001
        pass
    # Fallback: operator must fill in manually or set DIVIDE_WG_SERVER_PUBKEY.
    from app.core.config import settings as _s
    fallback = getattr(_s, "wg_server_pubkey", "") or "<server-public-key>"
    return fallback


__all__ = ["router"]
