#!/usr/bin/env python3
"""End-to-end live drill against a real PVE host.

Requires:
  * API reachable on http://localhost:8000 (override with --api-base)
  * PROXMOX_* env set in the API container (factory auto-picks real)
  * At least one VM template uploaded to PVE (use
    tools/upload_cloudinit_template.py to bootstrap one)
  * The drill token to have PVEVMAdmin on /v2/vm (PVEAuditor alone won't
    cut it for clone/start/stop/destroy)

What it does:
  1. Syncs scenarios from YAML -> DB (in case API was started before the
     scenarios were edited).
  2. Lists available scenarios, optionally filtered by --scenario.
  3. POSTs /api/v1/drills with the chosen scenario id.
  4. Polls /api/v1/drills every 2s until the run reaches a terminal state
     (succeeded / failed / cancelled) or --timeout s elapse.
  5. Prints the final Run + per-asset status.

Designed for one-off operator use, NOT CI. It hits live PVE and will
spin up real VMs. Run inside the API container:

    docker compose -f deploy/docker-compose.yml --env-file deploy/.env \
        exec api python /workdir/tools/live_drill.py \\
            --scenario phish-to-ransom --timeout 600
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx


REPO = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = os.environ.get("DIVIDE_API_BASE", "http://localhost:8000")


def _client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=10.0)


def _list_scenarios(client: httpx.Client, include_archived: bool = False) -> list[dict]:
    r = client.get(
        "/api/v1/scenarios",
        params={"include_archived": str(include_archived).lower()},
    )
    r.raise_for_status()
    data = r.json()
    # API returns {"items": [...]}; tolerate either shape.
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return data


def _start_drill(client: httpx.Client, scenario_id: int) -> dict:
    r = client.post("/api/v1/drills", json={"scenario_id": scenario_id})
    if not r.is_success:
        # Surface the API's error body, not just the HTTP status.
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = r.text
        raise RuntimeError(
            f"POST /api/v1/drills failed ({r.status_code}): {body}"
        )
    return r.json()


def _list_runs(client: httpx.Client) -> list[dict]:
    r = client.get("/api/v1/drills")
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return data


def _stop_drill(client: httpx.Client, run_id: int) -> dict:
    r = client.post(f"/api/v1/drills/{run_id}/stop")
    r.raise_for_status()
    return r.json()


def _wait_for_terminal(
    client: httpx.Client,
    run_id: int,
    timeout_s: float,
    poll_s: float = 2.0,
) -> dict | None:
    """Poll /api/v1/drills until the run is terminal. Return final state."""
    terminal = {"succeeded", "failed", "cancelled"}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runs = _list_runs(client)
        for r in runs:
            rid = r.get("run_id") or r.get("id")
            if rid == run_id:
                status = r.get("status", "").lower()
                print(
                    f"  [{int(deadline - time.monotonic()):>3}s left] "
                    f"run={run_id} status={status:<10} "
                    f"assets={r.get('asset_count', '?')}"
                )
                if status in terminal:
                    return r
                break
        time.sleep(poll_s)
    print(f"TIMEOUT after {timeout_s}s — run is still not terminal")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--api-base", default=DEFAULT_API_BASE, help="API base URL")
    ap.add_argument(
        "--scenario",
        default=None,
        help="Scenario name to run (default: first non-archived)",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for the run to finish (default 300)",
    )
    ap.add_argument(
        "--no-stop",
        action="store_true",
        help="Don't call /stop after the run finishes (handy for inspecting)",
    )
    ap.add_argument(
        "--list-only",
        action="store_true",
        help="Just list scenarios + recent runs and exit",
    )
    args = ap.parse_args()

    client = _client(args.api_base)

    # Health check first.
    try:
        h = client.get("/healthz")
        h.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot reach {args.api_base}: {exc}")
        return 2
    print(f"OK: API {h.json()}")

    scenarios = _list_scenarios(client)
    if not scenarios:
        print("FAIL: no scenarios in the catalog. Run 'make sync-scenarios'.")
        return 2

    print(f"OK: {len(scenarios)} scenarios in catalog:")
    for s in scenarios:
        archived = " [archived]" if s.get("archived_at") else ""
        print(f"  - {s['name']:<40} id={s['id']}{archived}")

    runs = _list_runs(client)
    print(f"OK: {len(runs)} recent runs")
    for r in runs[:5]:
        rid = r.get("run_id") or r.get("id")
        print(f"  - run id={rid:<4} status={r['status']:<10} scenario_id={r['scenario_id']}")

    if args.list_only:
        return 0

    chosen = None
    if args.scenario:
        for s in scenarios:
            if s["name"] == args.scenario:
                chosen = s
                break
        if chosen is None:
            print(f"FAIL: scenario {args.scenario!r} not in catalog")
            return 2
    else:
        # Pick the first non-archived.
        chosen = next((s for s in scenarios if not s.get("archived_at")), None)
        if chosen is None:
            print("FAIL: no non-archived scenarios")
            return 2

    print(f"-> starting drill: {chosen['name']} (id={chosen['id']})")
    started = _start_drill(client, chosen["id"])
    print(json.dumps(started, indent=2))
    run_id = started["run_id"]

    print(f"-> waiting for run {run_id} (timeout {args.timeout}s)...")
    final = _wait_for_terminal(client, run_id, timeout_s=args.timeout)
    if final is None:
        return 1

    print("-> final state:")
    print(json.dumps(final, indent=2))

    if args.no_stop or final.get("status") in ("succeeded", "failed", "cancelled"):
        return 0 if final.get("status") == "succeeded" else 1

    print("-> stopping run...")
    print(json.dumps(_stop_drill(client, run_id), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
