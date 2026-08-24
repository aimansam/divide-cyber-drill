"""Token auth for div:ide.

Token format: HMAC-SHA256-signed compact JWS-ish token::

    <base64url-payload>.<base64url-signature>

Payload (JSON, base64url-decoded)::

    {
      "sub": "alice",            # subject (user id)
      "role": "admin",           # role string (one of the Role enum values;
                                 # see app.core.auth.Role below)
      "iat": 1755000000,         # issued-at (unix seconds)
      "exp": 1755086400          # expires-at (unix seconds)
    }

Why HMAC over a full JWT lib: zero deps, small surface, easy to
test. A real lib (PyJWT, authlib) would add a dependency for very
little benefit at this scale -- the audience here is one LAN, five
roles (see :class:`Role`), no third-party identity provider.

Header convention: ``X-Divide-Token: <token>`` on every request that
wants to identify a user. Absence of the header means "anonymous".
Whether anonymous is allowed depends on the endpoint:

  * :func:`current_token` — passive; returns ``None`` when the header
    is missing. Use this in handlers that want to attribute audit /
    rate-limit rows but don't want to reject anonymous calls.
  * :func:`require_token` — active; returns ``HTTP 401`` when the
    header is missing. Use this as a hard gate on routes that
    require any identified caller.
  * :func:`require_role` — active; returns ``HTTP 401`` (no token)
    or ``HTTP 403`` (token role not in the allow-list). Use this on
    routes that require a *specific persona* (admin / lead / red /
    blue / observer).

The role taxonomy lives in :class:`Role`. ``tools/issue_token.py``
restricts ``--role`` to these values. Adding a new role is a
two-place change: append to :class:`Role` and update
``USER-REQUIREMENTS.md`` §2's permission matrix.

What auth does NOT do:
  * Track revocation. Tokens are valid until ``exp``. Future L2 work
    would add a token-bucket rejected list keyed by ``sub``.
  * Validate against an IdP. Self-signed is fine for LAN.
  * Gate ``/api/v1/proxmox/*``. Those endpoints remain anonymous on
    purpose in L2 (the setup wizard's step 1 hits ``/proxmox/health``
    from the operator's browser before any token is in scope). M5
    in the post-L1 plan owns the full ``/proxmox/*`` hardening pass;
    until then the router documents this with a one-line comment
    on each proxmox endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import settings


class Role(str, Enum):
    """The five persona roles on the div:ide control plane.

    The string values are the wire format — they appear in token
    payloads, in ``X-Divide-Token`` claim, in audit rows, and in
    ``tools/issue_token.py --role``. Changing a value here is a
    breaking change for every existing token. Add new values at
    the end; don't reorder.

    Mapping to the USER-REQUIREMENTS.md persona matrix:
      * ADMIN     — Platform Admin (operator + full powers)
      * LEAD      — Drill Lead (instructor, run lifecycle owner)
      * RED       — Red Team participant (offensive side)
      * BLUE      — Blue Team participant (defensive side)
      * OBSERVER  — Read-only (watching but not acting)

    The wizard's PVE-side ACL role (``PVEDatastoreAdmin``) is a
    different concept — it's a Proxmox-side RBAC string, not a
    div:ide role. Don't conflate them.
    """

    ADMIN = "admin"
    LEAD = "lead"
    RED = "red"
    BLUE = "blue"
    OBSERVER = "observer"

# Per-process fallback secret cache (used when neither divide_token_secret
# nor proxmox.token_secret is configured). Cached so sign_token and
# verify_token in the same process agree on the same secret.
_RANDOM_FALLBACK_SECRET: bytes | None = None


# ---------- token model ---------------------------------------------------

@dataclass(frozen=True)
class TokenData:
    """Decoded token payload."""

    sub: str
    role: str
    iat: int
    exp: int

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.exp


# ---------- sign + verify -----------------------------------------------

_BASE64_ALT = base64.urlsafe_b64encode
_BASE64_ALT_DECODE = base64.urlsafe_b64decode


def _b64encode(data: bytes) -> str:
    """URL-safe base64, no padding (JWS convention)."""
    return _BASE64_ALT(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    """URL-safe base64, no padding. Restores padding if needed."""
    pad = "=" * (-len(data) % 4)
    return _BASE64_ALT_DECODE((data + pad).encode("ascii"))


def _signing_secret() -> bytes:
    """Resolve the HMAC secret.

    Priority: explicit ``divide_token_secret`` env / settings value
    > derived from PROXMOX_TOKEN_SECRET (so a single env var does both)
    > per-process random fallback (with warning, dev only).

    The fallback is per-process so the secret is stable for the life
    of the API process but doesn't persist across restarts -- a
    deliberate trade-off: tokens are valid only as long as the process
    that minted them. Production should always set
    ``DIVIDE_TOKEN_SECRET`` explicitly.
    """
    explicit = settings.divide_token_secret
    if explicit:
        return explicit.get_secret_value().encode("utf-8")
    # Derive from Proxmox secret if present (so operators don't have
    # to set a second env var in dev). On production we'd never want
    # to leak the PVE secret -- so we issue a loud warning, and ops
    # should override.
    if settings.proxmox.token_secret:
        import warnings

        warnings.warn(
            "DIVIDE_TOKEN_SECRET is unset; falling back to a derivation of "
            "PROXMOX_TOKEN_SECRET. Set DIVIDE_TOKEN_SECRET explicitly in "
            "production -- the dev fallback is not security-grade.",
            stacklevel=2,
        )
        return hashlib.sha256(
            b"divide-token|" + settings.proxmox.token_secret.get_secret_value().encode("utf-8")
        ).digest()
    # No proxmox secret either -- cache a per-process random secret.
    # Cached so that one process's sign_token and verify_token agree
    # on the same secret. The cache lives in a closure below.
    global _RANDOM_FALLBACK_SECRET  # noqa: PLW0603
    if _RANDOM_FALLBACK_SECRET is not None:
        return _RANDOM_FALLBACK_SECRET
    import os

    pid_secret = os.environ.get("DIVIDE_TOKEN_DEV_SECRET")
    _RANDOM_FALLBACK_SECRET = (
        pid_secret.encode("utf-8") if pid_secret else os.urandom(32)
    )
    return _RANDOM_FALLBACK_SECRET


def sign_token(sub: str, role: str, ttl_s: int) -> str:
    """Mint a new token. ``sub`` is the user id; ``role`` is free-form
    (e.g. ``"trainee"`` or ``"admin"``). ``ttl_s`` is the lifetime in
    seconds from now.

    The signature covers the base64url-encoded payload only (JWS
    compact-style). Verifier recomputes over the same bytes.
    """
    if not sub or not isinstance(sub, str):
        raise ValueError("`sub` must be a non-empty string")
    if not role or not isinstance(role, str):
        raise ValueError("`role` must be a non-empty string")
    if ttl_s <= 0:
        raise ValueError("`ttl_s` must be positive")

    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + int(ttl_s),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(payload_bytes)
    sig = hmac.new(_signing_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str) -> TokenData:
    """Decode + verify a token. Raises ``AuthError`` on any failure.

    Failure modes:
      * malformed (no '.' separator)
      * bad signature
      * expired (exp <= now)
      * non-JSON payload
      * missing required field
    """
    if not token or not isinstance(token, str):
        raise AuthError("missing token")
    if "." not in token:
        raise AuthError("malformed token (expected 'payload.signature')")
    payload_b64, sig_b64 = token.rsplit(".", 1)
    if not payload_b64 or not sig_b64:
        raise AuthError("malformed token (empty segment)")
    expected_sig = hmac.new(
        _signing_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        actual_sig = _b64decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"bad signature encoding: {exc}") from exc
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise AuthError("invalid signature")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise AuthError(f"bad payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuthError("payload must be a JSON object")
    for required in ("sub", "role", "iat", "exp"):
        if required not in payload:
            raise AuthError(f"missing field: {required}")
    token_data = TokenData(
        sub=payload["sub"],
        role=payload["role"],
        iat=int(payload["iat"]),
        exp=int(payload["exp"]),
    )
    if token_data.is_expired():
        raise AuthError("expired")
    return token_data


class AuthError(Exception):
    """Raised by verify_token on any failure.

    Routers convert this into HTTP 401. Tests assert against the
    string in the exception message.
    """


# ---------- FastAPI dependency -------------------------------------------


async def current_token(
    request: Request,
    x_divide_token: Annotated[str | None, Header(alias="X-Divide-Token")] = None,
) -> TokenData | None:
    """Read the bearer token from the request and stash it on
    ``request.state.token`` so downstream code can access it without
    re-decoding.

    Returns ``None`` if the header is absent (anonymous caller).
    Raises ``HTTPException(401)`` if a token was supplied but failed
    to validate -- that's a real authentication failure, not an
    anonymous request.
    """
    if x_divide_token is None:
        request.state.token = None
        return None
    try:
        token = verify_token(x_divide_token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.token = token
    return token


def token_subject(request: Request) -> str | None:
    """Convenience accessor for handlers.

    Use as a regular function (not Depends) when the handler has
    already received ``request``. Avoids the awkward
    ``Depends(current_token)`` dance on routes that need the token
    but aren't gating on it.
    """
    return getattr(request.state, "token", None) and request.state.token.sub


async def require_token(
    token: Annotated[TokenData | None, Depends(current_token)],
) -> TokenData:
    """Hard-gate dependency: ``Depend`` on this if a route MUST be
    authenticated. Returns 401 if no valid token.

    Today the div:ide control plane only uses this for the future
    L2 work (rate-limit attribution, audit attribution); L1 routes
    remain open because the entire API is on a LAN. L2 will mark
    individual routes with this dependency.
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="this endpoint requires an X-Divide-Token header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def require_role(*allowed: Role) -> Callable:
    """Build a FastAPI dependency that gates a route on token role.

    Use as ``token=Depends(require_role(Role.ADMIN, Role.LEAD))``.
    Composes with :func:`require_token` (i.e. a missing header is a
    401, not a 403). The 401 / 403 split lets the wizard + curl
    scripts distinguish "I forgot to attach the token" from "I am
    not authorized for this endpoint", which is the difference
    between a config bug and an attempted privilege escalation.

    On 403 the response detail names both the caller's role and
    the allow-list. That's intentional: it's friendlier than a bare
    "Forbidden" in dev, and it doesn't leak anything the caller
    couldn't read from the source. In production behind a reverse
    proxy that scrubs error bodies you'd want to soften this, but
    we don't ship behind one today.

    Edge cases handled:
      * No ``allowed`` args → the dependency rejects every
        authenticated call (defensive default; same effect as
        not registering the route at all).
      * Unknown role string in the token (e.g. an old token issued
        before :class:`Role` was tightened) → 403, because it
        won't match any string in ``allowed_set``.
    """
    if not allowed:
        # Defensive: callers should always pass at least one role.
        # Failing closed prevents accidental "matches nothing".
        raise ValueError("require_role() needs at least one Role")

    allowed_set = frozenset(r.value for r in allowed)

    async def _dep(
        token: Annotated[TokenData, Depends(require_token)],
    ) -> TokenData:
        if token.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"role={token.role!r} not in "
                    f"{sorted(allowed_set)}; this endpoint requires one of: "
                    + ", ".join(sorted(allowed_set))
                ),
            )
        return token

    return _dep
