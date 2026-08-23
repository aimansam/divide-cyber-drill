"""Token auth for div:ide.

Token format: HMAC-SHA256-signed compact JWS-ish token::

    <base64url-payload>.<base64url-signature>

Payload (JSON, base64url-decoded)::

    {
      "sub": "alice",            # subject (user id)
      "role": "trainee",         # role string (free-form for L1; gate later)
      "iat": 1755000000,         # issued-at (unix seconds)
      "exp": 1755086400          # expires-at (unix seconds)
    }

Why HMAC over a full JWT lib: zero deps, small surface, easy to
test. A real lib (PyJWT, authlib) would add a dependency for very
little benefit at this scale -- the audience here is one LAN, two
roles, no third-party identity provider.

Header convention: ``X-Divide-Token: <token>`` on every request that
wants to identify a user. Absence of the header means "anonymous"
(allowed on L1 for the wizard + admin endpoints; required on /drills
+ /scenarios in the future).

What auth does NOT do:
  * Enforce role-based access. L2.3-2.9 are about having the wiring
    so future L2 work can layer on RBAC. Today any valid token is
    treated as "identified user".
  * Track revocation. Tokens are valid until ``exp``. For L2 we'd add
    a token-bucket rejected list keyed by ``sub``.
  * Validate against an IdP. Self-signed is fine for LAN.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import settings

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
