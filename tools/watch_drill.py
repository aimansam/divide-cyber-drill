#!/usr/bin/env python3
"""Watch a live drill via Prometheus (and fall back to API polling).

Designed to run in a second terminal while `make live-drill` runs in
the first. It exits 0 the moment the run reaches the desired terminal
outcome (succeeded by default), and non-zero otherwise.

Three modes:
  --outcome succeeded|failed|cancelled|started
      Wait until divide_runs_total{outcome=<outcome>} increases.
      Default: succeeded.

  --cancel-after N
      Cancel the run N seconds after it starts. Used to exercise the
      /drills/{id}/cancel endpoint mid-flight so Panel 3 of the
      Grafana dashboard populates. Requires a token with role in
      {admin, lead, red} -- see ``--token`` below.

  --api-poll
      Fall back to /api/v1/drills polling if Prometheus isn't reachable.

Auth (L2 2.9): /api/v1/drills/{id}/cancel is now gated on
``require_role(ADMIN, LEAD, RED)``. Anonymous calls return 401.
Pass the token via ``--token`` (highest priority) or
``DIVIDE_TOKEN`` env var (default). The Prometheus + ``/drills``
list endpoints remain anonymous, so only the cancel call needs
the header.

Typical usage:
  # Watch for the next succeeded run (no auth needed for read paths):
  python tools/watch_drill.py

  # Cancel any drill that starts, after 30s:
  DIVIDE_TOKEN=$(python tools/issue_token.py --user watch-bot --role lead)
  python tools/watch_drill.py --cancel-after 30 --token "$DIVIDE_TOKEN"

  # Wait for a specific scenario to succeed:
  python tools/watch_drill.py --scenario first-live-drill
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = os.environ.get("DIVIDE_API_BASE", "http://localhost:8000")
DEFAULT_PROM_BASE = os.environ.get("DIVIDE_PROM_BASE", "http://localhost:9090")
# Default token comes from DIVIDE_TOKEN; --token CLI flag overrides.
DEFAULT_TOKEN = os.environ.get("DIVIDE_TOKEN")


def _get_counter(prom_base, labels, name="divide_runs_total"):
    """Return current value of a labelled counter from Prometheus."""
    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
    expr = f"{name}{{{label_str}}}"
    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.get(f"{prom_base}/api/v1/query", params={"query": expr})
            if r.status_code != 200:
                return None
            data = r.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return 0.0
            return float(results[0]["value"][1])
    except Exception:
        return None


def _list_recent_runs(api_base, scenario=None, limit=5):
    with httpx.Client(timeout=5.0) as c:
        r = c.get(f"{api_base}/api/v1/drills")
        r.raise_for_status()
        runs = r.json().get("items") or []
    if scenario:
        runs = [r for r in runs if r.get("scenario_id") is not None]
        # Best-effort scenario filter via catalog lookup.
        try:
            with httpx.Client(timeout=5.0) as c:
                sc = c.get(f"{api_base}/api/v1/scenarios").json().get("items", [])
                sid_to_name = {s["id"]: s["name"] for s in sc}
                runs = [r for r in runs if sid_to_name.get(r["scenario_id"]) == scenario]
        except Exception:
            pass
    return runs[:limit]


def _latest_run_id(api_base, scenario=None):
    runs = _list_recent_runs(api_base, scenario=scenario, limit=1)
    if not runs:
        return None
    return runs[0].get("run_id") or runs[0].get("id")


def _cancel(api_base, run_id, token=None):
    """POST /api/v1/drills/{id}/cancel with an auth header.

    The endpoint is gated on ``require_role(ADMIN, LEAD, RED)`` since
    L2 2.9. Without a token, the call returns 401 and the cancel
    does nothing. The caller logs the HTTP code so the operator
    notices.

    Read paths used by this script (Prometheus + /api/v1/drills
    list) are still anonymous, so the token is only attached on the
    single cancel POST.
    """
    headers = {"X-Divide-Token": token} if token else {}
    with httpx.Client(timeout=10.0) as c:
        r = c.post(
            f"{api_base}/api/v1/drills/{run_id}/cancel",
            headers=headers,
        )
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument(
        "--api-base", default=DEFAULT_API_BASE
    )
    ap.add_argument(
        "--prom-base", default=DEFAULT_PROM_BASE
    )
    ap.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help=(
            "X-Divide-Token for the /drills/{id}/cancel call "
            "(role must be admin/lead/red). Falls back to the "
            "$DIVIDE_TOKEN env var. Read paths don't need a token."
        ),
    )
    ap.add_argument(
        "--outcome",
        default="succeeded",
        choices=["started", "succeeded", "failed", "cancelled", "timeout"],
        help="Outcome to wait for (default: succeeded)",
    )
    ap.add_argument(
        "--scenario",
        default=None,
        help="Only watch runs of this scenario (filters the latest run)",
    )
    ap.add_argument(
        "--cancel-after",
        type=float,
        default=None,
        metavar="SECONDS",
        help="If set, cancel the run SECONDS after it starts",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Overall timeout in seconds (default 600)",
    )
    ap.add_argument(
        "--api-poll",
        action="store_true",
        help="Use /api/v1/drills polling instead of Prometheus",
    )
    ap.add_argument(
        "--poll",
        type=float,
        default=2.0,
        help="Polling interval in seconds",
    )
    args = ap.parse_args()

    # Capture the baseline counter so we detect the *next* event.
    baseline = None
    if not args.api_poll:
        baseline = _get_counter(args.prom_base, {"outcome": args.outcome})
        if baseline is None:
            print(
                f"WARN: Prometheus unreachable at {args.prom_base}; "
                f"falling back to API polling"
            )
            args.api_poll = True
        else:
            print(f"OK: Prometheus reachable; baseline {args.outcome}={baseline}")

    started_at = time.monotonic()
    deadline = started_at + args.timeout
    cancel_at = (
        started_at + args.cancel_after if args.cancel_after is not None else None
    )
    cancel_sent = False
    last_run_id = _latest_run_id(args.api_base, args.scenario) if args.api_poll else None

    print(f"-> watching for outcome={args.outcome!r}, timeout={args.timeout:.0f}s")
    if args.cancel_after is not None:
        print(f"-> will cancel at t+{args.cancel_after}s")
        if not args.token:
            print(
                "WARN: --cancel-after requires an admin/lead/red token; "
                "set --token or $DIVIDE_TOKEN. The cancel call will "
                "return 401 without it."
            )

    while time.monotonic() < deadline:
        now = time.monotonic()
        elapsed = now - started_at

        if not args.api_poll:
            current = _get_counter(args.prom_base, {"outcome": args.outcome})
            if current is not None and baseline is not None and current > baseline:
                print(
                    f"\nSUCCESS: divide_runs_total{{outcome={args.outcome!r}}} "
                    f"moved {baseline} -> {current} after {elapsed:.1f}s"
                )
                return 0

        if cancel_at is not None and not cancel_sent and now >= cancel_at:
            rid = _latest_run_id(args.api_base, args.scenario)
            if rid is not None:
                code, body = _cancel(args.api_base, rid, token=args.token)
                print(f"\n[t+{elapsed:.1f}s] cancel -> HTTP {code}: {body}")
                cancel_sent = True
            else:
                print(f"[t+{elapsed:.1f}s] no run found to cancel yet")

        if args.api_poll:
            current_runs = _list_recent_runs(args.api_base, args.scenario, limit=1)
            if current_runs:
                rid = current_runs[0].get("run_id") or current_runs[0].get("id")
                status = current_runs[0].get("status", "")
                if rid != last_run_id:
                    last_run_id = rid
                    print(f"[t+{elapsed:.1f}s] new run: id={rid} status={status}")
                if status == args.outcome:
                    print(f"\nSUCCESS: run {rid} reached {status!r} after {elapsed:.1f}s")
                    return 0

        if int(elapsed) % 10 < args.poll:
            print(
                f"[t+{elapsed:.0f}s] waiting for outcome={args.outcome!r}"
                + (" (cancel armed)" if cancel_at and not cancel_sent else ""),
                end="\r",
                flush=True,
            )

        time.sleep(args.poll)

    print(f"\nTIMEOUT after {args.timeout:.0f}s waiting for outcome={args.outcome!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
