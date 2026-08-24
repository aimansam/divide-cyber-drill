"""Identity echo endpoint.

Phase 1: the portal renders "signed in as alice · red" by base64-
decoding the JWT payload client-side and trusting it for display.
That's a small but real footgun: an attacker who can MITM the
browser can show a different identity without breaking any signature.
The portal can't even tell whether the token is actually valid for
the API without doing a probe request.

Phase 2 (this file): the server has the verified answer on hand, so
we expose it. The endpoint is gated by ``require_token`` -- an
anonymous caller gets 401, same as every other authenticated
endpoint -- and the response is the decoded payload as the server
sees it (sub, role, iat, exp) plus a small ``ttl_remaining_s``
convenience field.

Why this is the right shape:

  * The payload is already signed by the API. The portal's
    client-side decode added nothing the API didn't already have.
  * Returning ``ttl_remaining_s`` lets the portal show "expires in
    27 minutes" without re-implementing the expiry math.
  * Returning the role string (not just a "verified: true" boolean)
    keeps the portal free of the role string constants -- the
    server is the source of truth.

Why this is *not* a session/whoami in the IdP sense:

  * No revocation list. A token is valid until ``exp`` regardless
    of what this endpoint says.
  * No lookup against a user database. ``sub`` is whatever the
    issuer put in the token; this endpoint doesn't validate that
    the user exists in any system.

For the M3.2 plan this lets the portal's TokenBar render a
"verified identity" badge instead of the unverified decode.
"""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import TokenData, current_token, require_token

router = APIRouter()


@router.get(
    "",
    summary="Return the verified identity for the bearer token",
    dependencies=[Depends(require_token)],
)
async def whoami(
    token: Annotated[TokenData, Depends(current_token)],
) -> dict:
    """Decoded + verified token payload, plus ``ttl_remaining_s``.

    Anonymous (no ``X-Divide-Token`` header or invalid token) ->
    ``HTTP 401`` from :func:`require_token`. Same shape as the rest
    of the authenticated API surface.
    """
    now = int(time.time())
    return {
        "sub": token.sub,
        "role": token.role,
        "iat": token.iat,
        "exp": token.exp,
        "ttl_remaining_s": max(0, token.exp - now),
    }