#!/usr/bin/env python3
"""Mint an X-Divide-Token by signing in with username + password.

F3-prep companion to ``issue_token.py``. Whereas ``issue_token.py``
signs tokens locally with the API's HMAC secret (the SSH-operator
flow), this script signs in via the API's credential-login endpoint
— the same flow the portal's SignInCard uses — and prints the
returned token.

Why a separate script:
  * ``issue_token.py`` works WITHOUT the API running (you can mint
    tokens before the stack is up). It uses the local HMAC secret.
  * This script REQUIRES the API to be up. It tests the full
    credential-login path including the argon2id hash + rate-limit.
  * For "I just changed the password, give me a token" use cases
    this script is the right tool. For "give me an admin token
    before the first user exists", use ``issue_token.py`` with the
    bootstrap admin secret.

Usage:
    python tools/login.py --user alice
    Password: ********
    <token>

Or non-interactive (CI):
    python tools/login.py --user alice --password hunter2

Or against a non-default API:
    python tools/login.py --user alice --api http://api:8000

Exit codes:
  0  success, token printed to stdout
  1  bad CLI args
  2  HTTP error (4xx, 5xx) — message printed to stderr
  3  network error
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API = "http://localhost:8000"


def _post_login(api: str, sub: str, password: str) -> dict:
    """POST /api/v1/auth/login and return the JSON body.

    Raises SystemExit on network errors or non-2xx responses. The
    token itself is in body['token'].
    """
    url = api.rstrip("/") + "/api/v1/auth/login"
    body = json.dumps({"sub": sub, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Try to extract the server's "detail" string for a friendly error.
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:  # noqa: BLE001
            pass
        print(
            f"error: login failed: HTTP {e.code} {e.reason}: {detail or '(no detail)'}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    except urllib.error.URLError as e:
        print(f"error: could not reach API at {api}: {e.reason}", file=sys.stderr)
        raise SystemExit(3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Sign in to div:ide and print an X-Divide-Token.",
    )
    ap.add_argument(
        "--user",
        required=True,
        help="Username (sub) to sign in as.",
    )
    ap.add_argument(
        "--password",
        default=None,
        help=(
            "Password. If omitted, the script prompts on the terminal. "
            "Pass --password only in trusted CI environments; it shows "
            "up in process listings."
        ),
    )
    ap.add_argument(
        "--api",
        default=DEFAULT_API,
        help=f"API base URL. Default: {DEFAULT_API}",
    )
    ap.add_argument(
        "--show-expiry",
        action="store_true",
        help=(
            "Print the exp timestamp and ttl_remaining_s alongside the "
            "token. Useful for verifying the credential-login response."
        ),
    )
    args = ap.parse_args(argv)

    password = args.password
    if password is None:
        # Prompt. If stdin isn't a TTY (CI), this raises; the caller
        # should pass --password in that case.
        try:
            password = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt) as e:
            print(f"error: no password supplied ({type(e).__name__})", file=sys.stderr)
            return 1

    resp = _post_login(args.api, args.user, password)

    # Single-line token output (mirrors issue_token.py).
    print(resp["token"])
    if args.show_expiry:
        print(
            f"# sub={resp['sub']} role={resp['role']} "
            f"exp={resp['exp']} ttl_remaining_s={resp['ttl_remaining_s']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
