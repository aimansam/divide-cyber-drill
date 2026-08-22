#!/usr/bin/env python3
"""Standalone Proxmox smoke test.

Usage:
    PROXMOX_HOST=... PROXMOX_TOKEN_ID=... PROXMOX_TOKEN_SECRET=... \
        python services/api/scripts/proxmox-smoke.py

Exits 0 if reachable, 1 otherwise. Never raises.
"""
from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    host = os.environ.get("PROXMOX_HOST")
    token_id = os.environ.get("PROXMOX_TOKEN_ID")
    token_secret = os.environ.get("PROXMOX_TOKEN_SECRET")
    user = os.environ.get("PROXMOX_USER", "divide@pve")
    port = int(os.environ.get("PROXMOX_PORT", "8006"))
    verify_ssl = os.environ.get("PROXMOX_VERIFY_SSL", "true").lower() in ("1", "true, true")

    if not (host and token_id and token_secret):
        print("ERROR: PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET must be set")
        return 1

    try:
        from proxmoxer import ProxmoxAPI

        client = ProxmoxAPI(
            host=host,
            port=port,
            user=user,
            token_name=token_id,
            token_value=token_secret,
            verify_ssl=verify_ssl,
            backend="https",
        )
        version = client.version()
        nodes = client.nodes.get()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        return 1

    print("OK: Proxmox reachable")
    print(f"     version : {version.get('version')} (release {version.get('release')})")
    print(f"     nodes   : {len(nodes)}")
    for n in nodes:
        print(f"       - {n['node']:20s} status={n['status']:6s} level={n.get('level', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
