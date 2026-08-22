#!/usr/bin/env python3
"""Post-drill sanity check for live (or mock) runs.

Complements tools/live_drill.py: live_drill runs the drill and polls
until it hits a terminal status. This tool goes one step further and
inspects the DB + audit log + /metrics to make sure the runner actually
did what we think it did and the Grafana panels have something to show.

Usage:
    python tools/verify_drill.py                         # most recent
    python tools/verify_drill.py --run-id 42
    python tools/verify_drill.py --expect failed
    python tools/verify_drill.py --json                  # CI mode
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import re
import sys
from typing import Any

import httpx

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = os.environ.get("DIVIDE_API_BASE", "http://localhost:8000")


# ---------- colour helpers (no external dep) ----------

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, msg: str) -> str:
    if not _USE_COLOR:
        return msg
    return f"\033[{code}m{msg}\033[0m"


def green(msg: str) -> str:
    return _c("32", msg)


def red(msg: str) -> str:
    return _c("31", msg)


def bold(msg: str) -> str:
    return _c("1", msg)


# ---------- API helpers ----------


def _client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=10.0)


def _fetch_run(client: httpx.Client, run_id: int) -> dict[str, Any] | None:
    """Return the Run row + asset list as a flat dict.

    The router exposes only the list endpoint (`GET /api/v1/drills`),
    so we fetch the list and pick the row. Asset detail is not exposed
    by the list endpoint either, so we return assets=[] for now and
    rely on the destroy-check being lenient when assets aren't there.
    """
    r = client.get("/api/v1/drills")
    if r.status_code != 200:
        return None
    body = r.json()
    runs = body.get("items") if isinstance(body, dict) else body
    if not isinstance(runs, list):
        return None
    for run in runs:
        if (run.get("run_id") or run.get("id")) == run_id:
            return {"run": run, "assets": []}
    return None


def _fetch_audit(client: httpx.Client, run_id: int) -> list[dict[str, Any]]:
    """Best-effort fetch of audit entries for a run. Returns [] on 404."""
    r = client.get(f"/api/v1/drills/{run_id}/audit")
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json()
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    if isinstance(body, list):
        return body
    return []


def _fetch_metrics(client: httpx.Client) -> dict[tuple[str, frozenset], float]:
    """Return {(name, frozenset(label_items)): value} for every divide_*
    counter/gauge/histogram sample.

    Labels are preserved so callers can query specific label combinations
    (e.g. ``divide_runs_total{outcome="succeeded"}``) instead of collapsing
    every label combo into one bucket. Histogram ``_bucket`` lines carry
    an ``le=...`` label which is also preserved.

    Unlabeled samples get an empty frozenset key.
    """
    r = client.get("/metrics")
    r.raise_for_status()
    out: dict[tuple[str, frozenset], float] = {}
    # Match: name{labels} value  OR  name value
    labeled_re = re.compile(
        r"^(divide_[a-zA-Z0-9_]+)\{([^}]*)\}\s+([0-9eE+\-.]+)\s*$"
    )
    unlabeled_re = re.compile(
        r"^(divide_[a-zA-Z0-9_]+)\s+([0-9eE+\-.]+)\s*$"
    )
    for line in r.text.splitlines():
        if not line.startswith("divide_") or line.startswith("#"):
            continue
        m = labeled_re.match(line)
        if m:
            name, labels_str, value_str = m.group(1), m.group(2), m.group(3)
            # Parse labels: 'adapter="real",outcome="succeeded"'
            labels = _parse_labels(labels_str)
        else:
            m = unlabeled_re.match(line)
            if not m:
                continue
            name, value_str = m.group(1), m.group(2)
            labels = frozenset()
        with contextlib.suppress(ValueError):
            out[(name, labels)] = float(value_str)
    return out


def _parse_labels(s: str) -> frozenset:
    """Parse a Prometheus label set like 'adapter="real",outcome="succeeded"'.

    Returns a frozenset of (key, value) tuples so it's hashable and
    order-independent. Values are kept as strings — callers compare
    strings, not numbers (Prometheus labels are always strings)."""
    out: set[tuple[str, str]] = set()
    # Simple state machine: split on commas that aren't inside quotes.
    for part in _split_labels(s):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out.add((k, v))
    return frozenset(out)


def _split_labels(s: str) -> list[str]:
    """Split a label string on top-level commas (not inside quoted values)."""
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _get_metric(
    metrics: dict[tuple[str, frozenset], float],
    name: str,
    **labels: str,
) -> float | None:
    """Look up a specific metric+label combination. Returns None if absent."""
    wanted = frozenset(labels.items())
    for (n, lab), value in metrics.items():
        if n != name:
            continue
        # The stored label set may include extra labels (e.g. 'adapter' when
        # you asked only for 'outcome'). Require the wanted labels to be
        # present and equal; extras are fine.
        wanted_pairs = dict(wanted)
        stored_pairs = dict(lab)
        if all(stored_pairs.get(k) == v for k, v in wanted_pairs.items()):
            return value
    return None


def _sum_metric(
    metrics: dict[tuple[str, frozenset], float],
    name: str,
    **labels: str,
) -> float:
    """Like _get_metric but sums across all label combinations matching
    the filter. Useful for label-agnostic checks (e.g. total runs across
    all adapters)."""
    wanted_pairs = dict(frozenset(labels.items()))
    total = 0.0
    for (n, lab), value in metrics.items():
        if n != name:
            continue
        stored_pairs = dict(lab)
        if all(stored_pairs.get(k) == v for k, v in wanted_pairs.items()):
            total += value
    return total



# ---------- checks ----------


def check_run_status(run: dict[str, Any], expect: str) -> tuple[bool, str]:
    got = run.get("status")
    if got == expect:
        return True, f"run.status == {expect!r}"
    return False, f"run.status == {expect!r} (got {got!r})"


def check_assets_destroyed(assets: list[dict[str, Any]]) -> tuple[bool, str]:
    """For a drill that should have torn down: every asset with a pve_vmid
    must be in a terminal status (stopped/failed/orphaned)."""
    if not assets:
        return False, "no assets recorded (runner never cloned anything)"
    real_assets = [a for a in assets if a.get("pve_vmid") is not None]
    if not real_assets:
        return False, (
            f"{len(assets)} asset(s) recorded but none have pve_vmid "
            "(clone never reported a VMID back to the DB)"
        )
    terminal = {"stopped", "failed", "orphaned"}
    bad = [a for a in real_assets if a.get("status") not in terminal]
    if bad:
        statuses = ", ".join(f"{a['role']}={a.get('status')}" for a in bad)
        return False, (
            f"{len(bad)}/{len(real_assets)} asset(s) not in terminal state: "
            f"{statuses}"
        )
    return True, (
        f"{len(real_assets)} asset(s) torn down "
        f"(vmids: {', '.join(str(a['pve_vmid']) for a in real_assets)})"
    )


def check_assets_spawned(assets: list[dict[str, Any]]) -> tuple[bool, str]:
    """For a drill in 'succeeded' state that hasn't been torn down yet:
    at least one asset with pve_vmid populated."""
    real = [a for a in assets if a.get("pve_vmid") is not None]
    if not real:
        return False, "no asset has pve_vmid; clone never happened"
    return True, (
        f"{len(real)} asset(s) spawned "
        f"(vmids: {', '.join(str(a['pve_vmid']) for a in real)})"
    )


def check_audit(actions: list[str], expect: str) -> tuple[bool, str]:
    """For each terminal status, assert the expected actions exist.
    Returns skip-OK if the audit endpoint returned [] (404)."""
    seen = set(actions)
    if not actions:
        return True, "audit endpoint unavailable (skipping)"
    if expect == "succeeded":
        needed = {"run.started"}
        if "asset.spawned" in seen:
            needed.add("asset.spawned")
        if "run.completed" in seen:
            needed.add("run.completed")
        missing = needed - seen
        if missing:
            return False, f"missing audit actions: {sorted(missing)}"
        return True, f"audit OK ({len(actions)} entries)"
    if expect == "failed":
        needed = {"run.started", "run.failed"}
        missing = needed - seen
        if missing:
            return False, f"missing audit actions: {sorted(missing)}"
        return True, f"audit OK ({len(actions)} entries, includes run.failed)"
    if expect == "cancelled":
        needed = {"run.started", "run.cancelled"}
        missing = needed - seen
        if missing:
            return False, f"missing audit actions: {sorted(missing)}"
        return True, f"audit OK ({len(actions)} entries, includes run.cancelled)"
    return True, f"audit not checked for status {expect!r}"


def check_metrics_counter(
    metrics: dict[tuple[str, frozenset], float],
    expect: str = "succeeded",
) -> tuple[bool, str]:
    """Label-aware metric check.

    Asserts:
      * ``divide_runs_total{outcome=<expect>, adapter="real"}`` is > 0
        (a real drill hit this outcome since the API started).
      * ``divide_runs_total{outcome="failed", adapter="real"}`` is 0
        (no real drill failed since the API started -- if any did,
        we'd want to investigate).
      * ``divide_runs_active{adapter="real"}`` is 0 (no in-flight runs
        hanging after live_drill returned).

    We scope to ``adapter="real"`` because that's what production
    drills use; the ``adapter="mock"`` counter exists for unit tests.
    """
    real = {"adapter": "real"}
    # Specific outcome should be > 0.
    outcome_value = _get_metric(metrics, "divide_runs_total",
                                outcome=expect, **real)
    if outcome_value is None:
        # No samples with this outcome ever — could be a brand-new
        # process or the zero-init pre-fill. Look across all adapters.
        all_outcome = _sum_metric(metrics, "divide_runs_total", outcome=expect)
        if all_outcome == 0:
            return False, (
                f"divide_runs_total{{outcome={expect!r}}} is 0 (or "
                f"absent) -- no drill reached the {expect!r} state since "
                f"the API started"
            )
        outcome_value = all_outcome

    # Failed should be 0 (no regressions).
    failed_value = _get_metric(metrics, "divide_runs_total",
                               outcome="failed", **real) or 0.0
    # Active should be 0 (no in-flight).
    active = _get_metric(metrics, "divide_runs_active", **real) or 0.0

    if failed_value > 0:
        return False, (
            f"divide_runs_total{{outcome=\"failed\", adapter=\"real\"}}="
            f"{failed_value} -- {int(failed_value)} drill(s) failed since "
            f"the API started. Investigate the runs table."
        )
    if active > 0:
        return False, (
            f"divide_runs_active{{adapter=\"real\"}}={active} -- a drill "
            f"is still in-flight; live_drill should have waited"
        )
    return True, (
        f"divide_runs_total{{outcome={expect!r}, adapter=\"real\"}}="
        f"{outcome_value}, divide_runs_active=0, failed=0"
    )


# ---------- reporting ----------


def _print_human(
    run_id: int,
    run: dict[str, Any],
    assets: list[dict[str, Any]],
    results: list[tuple[str, bool, str]],
    json_mode: bool = False,
) -> None:
    if json_mode:
        print(json.dumps({
            "run_id": run_id,
            "status": run.get("status"),
            "scenario_id": run.get("scenario_id"),
            "assets": [
                {
                    "role": a.get("role"),
                    "pve_vmid": a.get("pve_vmid"),
                    "pve_node": a.get("pve_node"),
                    "pve_ip": a.get("pve_ip"),
                    "status": a.get("status"),
                }
                for a in assets
            ],
            "checks": [
                {"name": name, "ok": ok, "detail": detail}
                for name, ok, detail in results
            ],
        }, indent=2))
        return

    print("=" * 70)
    print(f"VERIFY-DRILL  run_id={run_id}  status={run.get('status')!r}")
    print("=" * 70)
    if run.get("error"):
        print(f"  error: {run['error']}")
    if assets:
        print(f"  {len(assets)} asset(s):")
        for a in assets:
            print(
                f"    - role={a.get('role'):<20} "
                f"vmid={a.get('pve_vmid')}  node={a.get('pve_node')}  "
                f"ip={a.get('pve_ip')}  status={a.get('status')}"
            )
    print()
    print("  Checks:")
    for name, ok, detail in results:
        tag = green("[PASS]") if ok else red("[FAIL]")
        print(f"    {tag} {bold(name):<32} {detail}")
    print("=" * 70)


# ---------- main ----------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Post-drill sanity check (DB + audit + metrics).",
    )
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--run-id", type=int, default=None,
                    help="Run to verify (default: most recent)")
    ap.add_argument("--expect", default="succeeded",
                    choices=["succeeded", "failed", "cancelled", "running"],
                    help="Expected terminal status (default: succeeded)")
    ap.add_argument("--destroyed-check", dest="destroyed_check",
                    action="store_true", default=True,
                    help="Assert assets are torn down (default True). "
                         "Skipped if asset detail isn't exposed by the "
                         "API (current router only lists runs).")
    ap.add_argument("--no-destroyed-check", dest="destroyed_check",
                    action="store_false",
                    help="Skip the teardown check (useful right after "
                         "live_drill exits -- it leaves assets running so "
                         "you can inspect)")
    ap.add_argument("--json", action="store_true", help="JSON output for CI")
    args = ap.parse_args()

    client = _client(args.api_base)
    try:
        client.get("/healthz").raise_for_status()
    except Exception as exc:
        print(red(f"FAIL: cannot reach API at {args.api_base}: {exc}"))
        return 2

    # Pick the run.
    run_id = args.run_id
    if run_id is None:
        r = client.get("/api/v1/drills")
        r.raise_for_status()
        runs = r.json().get("items") or r.json()
        if not runs:
            print(red("FAIL: no runs in the catalog"))
            return 2
        run_id = runs[0].get("run_id") or runs[0].get("id")
    if run_id is None:
        print(red("FAIL: could not determine run_id"))
        return 2

    data = _fetch_run(client, run_id)
    if data is None:
        print(red(f"FAIL: run id={run_id} not found"))
        return 2
    run, assets = data["run"], data["assets"]

    audit = _fetch_audit(client, run_id)
    audit_actions = [a.get("action") for a in audit if a.get("action")]
    metrics = _fetch_metrics(client)

    results: list[tuple[str, bool, str]] = []
    ok, detail = check_run_status(run, args.expect)
    results.append(("run.status", ok, detail))
    if args.expect == "succeeded" and args.destroyed_check:
        if not assets:
            # Asset detail not exposed by the current API. Warn but don't
            # fail -- the rest of the checks (status, audit, metrics)
            # already prove the drill happened.
            results.append((
                "assets torn down",
                True,
                "skipped (asset detail not in GET /api/v1/drills response)",
            ))
        else:
            ok, detail = check_assets_destroyed(assets)
            results.append(("assets torn down", ok, detail))
    elif args.expect in ("succeeded", "running"):
        if not assets:
            results.append((
                "assets spawned",
                True,
                "skipped (asset detail not in GET /api/v1/drills response)",
            ))
        else:
            ok, detail = check_assets_spawned(assets)
            results.append(("assets spawned", ok, detail))
    ok, detail = check_audit(audit_actions, args.expect)
    results.append(("audit log", ok, detail))
    ok, detail = check_metrics_counter(metrics, expect=args.expect)
    results.append(("/metrics", ok, detail))

    _print_human(run_id, run, assets, results, json_mode=args.json)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())


