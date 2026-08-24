#!/usr/bin/env python3
"""Issue a div:ide token for a user.

Tokens are HMAC-SHA256-signed compact JWS-ish strings. They go in the
``X-Divide-Token`` request header on API calls that need a known
caller identity (rate limiting, audit attribution, RBAC).

Usage:
    python tools/issue_token.py --user alice --role red --ttl 24h
    python tools/issue_token.py --user bob --role admin --ttl 7d
    python tools/issue_token.py --user charlie --role lead --ttl 12h

The ``--role`` choices are the five :class:`app.core.auth.Role`
enum values: ``admin``, ``lead``, ``red``, ``blue``, ``observer``.
Anything else is rejected at the CLI (L2 2.9).

The token is signed with the same secret the API uses to verify
tokens (resolved from ``DIVIDE_TOKEN_SECRET`` or derived from
``PROXMOX_TOKEN_SECRET``). The CLI prints the token to stdout so the
caller can copy it. There's no separate ``--write-to-file`` flag; the
output is a single line and trivially ``> token.txt`` --able.

Why a script and not an HTTP endpoint:
  * Operators need tokens BEFORE the API is running (e.g. they're
    about to start the API for the first time). An HTTP endpoint
    would be self-referential.
  * The CLI is testable without a stack.
  * A future ``divide`` console can wrap this script.

What this does NOT do:
  * Persist tokens. They're stateless HMACs; the API verifies on every
    request.
  * Revoke tokens. Expiry is the only mechanism today; revocation
    lists are L2 work.
  * Sign in with a password. For that flow, see ``tools/login.py``
    (F3-prep). The two tools are complementary: this script mints
    tokens locally with the HMAC secret; ``tools/login.py`` goes
    through the API's credential-login endpoint and exercises the
    argon2id + rate-limit path.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root on path so we can import app.core.auth without an editable
# install (tools/ runs from the dev box where the package isn't pip-installed).
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.core.auth import sign_token  # noqa: E402


def _parse_ttl(spec: str) -> int:
    """Parse a duration like ``24h``, ``7d``, ``30m``, or ``3600``
    into seconds. Bare integers are treated as seconds.
    """
    s = spec.strip()
    if not s:
        raise SystemExit("error: empty --ttl value")
    unit = s[-1].lower()
    if unit.isdigit():
        return int(s)
    if len(s) < 2:
        raise SystemExit(f"error: bad --ttl {spec!r}")
    n = int(s[:-1])
    if n <= 0:
        raise SystemExit(f"error: --ttl must be positive, got {spec!r}")
    if unit == "s":
        return n
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 86400
    raise SystemExit(
        f"error: bad --ttl unit {unit!r}; expected s/m/h/d suffix (or no suffix for seconds)"
    )


def main(argv: list[str] | None = None) -> int:
    from app.core.auth import Role

    ap = argparse.ArgumentParser(
        description="Issue a div:ide X-Divide-Token for a user.",
    )
    ap.add_argument(
        "--user",
        required=True,
        help="Subject (user id) the token identifies. Free-form string.",
    )
    ap.add_argument(
        "--role",
        default=Role.RED.value,
        choices=[r.value for r in Role],
        help=(
            "Role string the token carries. Must be one of the "
            "Role enum values (L2 2.9); default red. The legacy "
            "'trainee' value is rejected -- re-issue with --role red "
            "or blue instead."
        ),
    )
    ap.add_argument(
        "--ttl",
        default="24h",
        help="Token lifetime. Suffixes s/m/h/d; bare integers are seconds. Default 24h.",
    )
    args = ap.parse_args(argv)

    ttl_s = _parse_ttl(args.ttl)
    token = sign_token(sub=args.user, role=args.role, ttl_s=ttl_s)
    # Single-line output so callers can do `divide issue-token --user x > x.token`.
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
