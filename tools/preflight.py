#!/usr/bin/env python3
"""Pre-flight gate for `make live-drill`.

Returns exit code 0 if all pre-conditions hold, 1 otherwise.

Checks (each one prints PASS / FAIL with a one-line reason):
  [1] /healthz responds 200
  [2] PROXMOX_* configured (RealProxmoxAdapter selected)
  [3] PVE nodes reachable via the adapter
  [4] Template `tpl-debian-cloudinit` exists on PVE (or --template)
  [5] Scenario `first-live-drill` in DB (or --scenario)
  [6] /metrics endpoint live
  [7] Prometheus scraping divide-api
  [8] Grafana dashboard loaded (UID divide-drill-platform)

Each check is independent -- we run them all so you see every red flag,
not just the first. The summary at the end tells you what to fix.

    python tools/preflight.py
    python tools/preflight.py --scenario phish-to-ransom
    python tools/preflight.py --template tpl-ubuntu-2204
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = os.environ.get("DIVIDE_API_BASE", "http://localhost:8000")
DEFAULT_PROM_BASE = os.environ.get("DIVIDE_PROM_BASE", "http://localhost:9090")
DEFAULT_GRAFANA_BASE = os.environ.get("DIVIDE_GRAFANA_BASE", "http://localhost:3000")
GRAFANA_USER = os.environ.get("GRAFANA_ADMIN_USER", "admin")
GRAFANA_PASS = os.environ.get("GRAFANA_ADMIN_PASSWORD", "divide")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    hint: str = ""


@dataclass
class Report:
    results: list = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "", hint: str = "") -> None:
        self.results.append(CheckResult(name, passed, detail, hint))

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    def print_summary(self) -> None:
        print()
        print("=" * 70)
        print("PRE-FLIGHT REPORT")
        print("=" * 70)
        max_name = max(len(r.name) for r in self.results) + 2
        for r in self.results:
            tag = "PASS" if r.passed else "FAIL"
            line = f"  [{tag}] {r.name:<{max_name}} {r.detail}"
            print(line)
            if not r.passed and r.hint:
                print(f"         -> {r.hint}")
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print("-" * 70)
        print(f"  {passed}/{total} checks passed")
        if self.all_passed:
            print("  READY for live drill. Run: make live-drill")
        else:
            print("  NOT READY. Fix the FAIL items above and re-run.")
        print("=" * 70)


# --- individual checks ---------------------------------------------------


def check_api_health(client, report):
    try:
        r = client.get("/healthz", timeout=5.0)
        if r.status_code != 200:
            report.add(
                "/healthz responds 200",
                False,
                f"HTTP {r.status_code}",
                "Is the api container up? Try: docker compose -f deploy/docker-compose.yml ps",
            )
            return
        body = r.json()
        report.add(
            "/healthz responds 200",
            True,
            f"env={body.get('env','?')}, version={body.get('version','?')}",
        )
    except Exception as exc:
        report.add(
            "/healthz responds 200",
            False,
            f"connection error: {exc}",
            f"Is the API reachable at {client.base_url}?",
        )


def check_prom_env(client, report):
    try:
        r = client.get("/api/v1/proxmox/health", timeout=5.0)
        if r.status_code == 200:
            body = r.json()
            report.add(
                "PROXMOX_* configured (RealProxmoxAdapter)",
                True,
                f"version={body.get('version', '?')}, ok={body.get('ok', '?')}",
            )
        elif r.status_code == 503:
            report.add(
                "PROXMOX_* configured (RealProxmoxAdapter)",
                False,
                "PROXMOX_HOST empty / adapter is MockProxmoxAdapter",
                "Set PROXMOX_HOST/PORT/USER/TOKEN_ID/TOKEN_SECRET in deploy/.env, "
                "then: docker compose up -d api",
            )
        else:
            report.add(
                "PROXMOX_* configured (RealProxmoxAdapter)",
                False,
                f"unexpected HTTP {r.status_code}",
                "Check API logs: docker compose logs api --tail 50",
            )
    except Exception as exc:
        report.add(
            "PROXMOX_* configured (RealProxmoxAdapter)",
            False,
            f"request failed: {exc}",
        )


def check_pve_nodes(client, report):
    try:
        r = client.get("/api/v1/proxmox/nodes", timeout=10.0)
        if r.status_code != 200:
            report.add(
                "PVE nodes reachable",
                False,
                f"HTTP {r.status_code}: {r.text[:120]}",
                "Likely a PVE auth or network issue. Test from dev box: curl -k "
                "https://<pve>:8006/api2/json/nodes -H 'Authorization: ...'",
            )
            return
        body = r.json()
        nodes = body.get("items") or body.get("nodes") or []
        if not nodes:
            report.add(
                "PVE nodes reachable",
                False,
                "PVE returned 0 nodes",
                "Is the cluster running? Check PVE GUI.",
            )
        else:
            report.add(
                "PVE nodes reachable",
                True,
                f"{len(nodes)} node(s): {', '.join(n.get('node','?') for n in nodes)}",
            )
    except Exception as exc:
        report.add(
            "PVE nodes reachable",
            False,
            f"request failed: {exc}",
        )


def check_template_exists(client, name, report):
    try:
        r = client.get("/api/v1/proxmox/templates", timeout=10.0)
        if r.status_code != 200:
            report.add(
                f"Template {name!r} exists on PVE",
                False,
                f"HTTP {r.status_code}",
                "Need PVEAuditor (or broader) on / for the templates endpoint to work",
            )
            return
        body = r.json()
        templates = body.get("items") or body.get("templates") or []
        names = {t.get("name") for t in templates}
        if name in names:
            vmid = next((t.get("vmid") for t in templates if t.get("name") == name), "?")
            report.add(
                f"Template {name!r} exists on PVE",
                True,
                f"vmid={vmid}",
            )
        else:
            similar = [n for n in names if name.split("-")[0].lower() in n.lower()]
            detail = (
                f"not found. Available templates: {sorted(names)[:8]}"
                if not similar
                else f"not found. Did you mean: {similar}?"
            )
            report.add(
                f"Template {name!r} exists on PVE",
                False,
                detail,
                f"Upload it: make upload-template NAME={name} "
                f"ISO=local:iso/<your-debian.iso>. Then install Debian "
                f"in the PVE GUI + apt install qemu-guest-agent + shutdown. "
                f"Then re-run: make upload-template NAME={name} "
                f"(--convert-only VMID will be printed by the first run).",
            )
    except Exception as exc:
        report.add(
            f"Template {name!r} exists on PVE",
            False,
            f"request failed: {exc}",
        )


def check_scenario_in_db(client, name, report):
    try:
        r = client.get("/api/v1/scenarios", timeout=5.0)
        if r.status_code != 200:
            report.add(
                f"Scenario {name!r} in DB",
                False,
                f"HTTP {r.status_code}",
            )
            return
        items = r.json().get("items") or []
        match = next(
            (s for s in items if s.get("name") == name and not s.get("archived_at")),
            None,
        )
        if match is None:
            names = [s.get("name") for s in items if not s.get("archived_at")]
            report.add(
                f"Scenario {name!r} in DB",
                False,
                f"not found. Available: {names}",
                "Sync from YAML: make sync-scenarios",
            )
        else:
            sid = match.get("id")
            report.add(
                f"Scenario {name!r} in DB",
                True,
                f"id={sid}",
            )
    except Exception as exc:
        report.add(
            f"Scenario {name!r} in DB",
            False,
            f"request failed: {exc}",
        )


def check_metrics_live(client, report):
    try:
        r = client.get("/metrics", timeout=5.0)
        if r.status_code != 200:
            report.add(
                "/metrics live on API",
                False,
                f"HTTP {r.status_code}",
            )
            return
        body = r.text
        families = [line for line in body.splitlines() if line.startswith("# TYPE divide_")]
        if not families:
            report.add(
                "/metrics live on API",
                False,
                "no divide_* metric families in exposition",
                "Was the app built with prometheus-client installed?",
            )
        else:
            report.add(
                "/metrics live on API",
                True,
                f"{len(families)} divide_* metric families, {len(body)} bytes total",
            )
    except Exception as exc:
        report.add(
            "/metrics live on API",
            False,
            f"request failed: {exc}",
        )


def check_prometheus_scrape(report, target="divide-api"):
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{DEFAULT_PROM_BASE}/api/v1/targets?state=active")
            if r.status_code != 200:
                report.add(
                    "Prometheus scraping divide-api",
                    False,
                    f"HTTP {r.status_code} from {DEFAULT_PROM_BASE}",
                    f"Is Prometheus up? curl {DEFAULT_PROM_BASE}/-/ready",
                )
                return
            data = r.json()
            for t in data.get("data", {}).get("activeTargets", []):
                if t.get("labels", {}).get("job") == target:
                    if t.get("health") == "up":
                        url = t.get("scrapeUrl", "?")
                        report.add(
                            "Prometheus scraping divide-api",
                            True,
                            f"{url} -> up",
                        )
                    else:
                        last_err = (t.get("lastError") or "").strip()
                        report.add(
                            "Prometheus scraping divide-api",
                            False,
                            f"health={t.get('health')!r}, lastError={last_err[:80]}",
                            "Check deploy/prometheus/prometheus.yml -- is api:8000 resolvable "
                            "from the prometheus container?",
                        )
                    return
            report.add(
                "Prometheus scraping divide-api",
                False,
                f"target {target!r} not in active scrape list",
                "deploy/prometheus/prometheus.yml must declare a job named 'divide-api'",
            )
    except Exception as exc:
        report.add(
            "Prometheus scraping divide-api",
            False,
            f"request failed: {exc}",
            "Is Prometheus on :9090? Try: docker compose ps prometheus",
        )


def check_grafana_dashboard(report, uid="divide-drill-platform"):
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(
                f"{DEFAULT_GRAFANA_BASE}/api/dashboards/uid/{uid}",
                auth=(GRAFANA_USER, GRAFANA_PASS),
            )
            if r.status_code == 200:
                dash = r.json().get("dashboard", {})
                panels = len(dash.get("panels", []))
                report.add(
                    f"Grafana dashboard {uid!r} loaded",
                    True,
                    f"title={dash.get('title','?')!r}, panels={panels}",
                )
            elif r.status_code == 404:
                report.add(
                    f"Grafana dashboard {uid!r} loaded",
                    False,
                    "404 -- not provisioned",
                    "Is deploy/grafana/provisioning/dashboards/divide.yml mounted into "
                    "the grafana container?",
                )
            else:
                report.add(
                    f"Grafana dashboard {uid!r} loaded",
                    False,
                    f"HTTP {r.status_code}",
                )
    except Exception as exc:
        report.add(
            f"Grafana dashboard {uid!r} loaded",
            False,
            f"request failed: {exc}",
        )


# --- entrypoint ----------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--scenario", default="first-live-drill")
    ap.add_argument("--template", default="tpl-debian-cloudinit")
    args = ap.parse_args()

    report = Report()

    with httpx.Client(base_url=args.api_base, timeout=10.0) as client:
        check_api_health(client, report)
        check_prom_env(client, report)
        if any(r.name.startswith("PROXMOX") and r.passed for r in report.results):
            check_pve_nodes(client, report)
            check_template_exists(client, args.template, report)
        else:
            report.add(
                "PVE nodes reachable",
                False,
                "skipped (PROXMOX not configured)",
                "Fix the PROXMOX check first.",
            )
            report.add(
                f"Template {args.template!r} exists on PVE",
                False,
                "skipped (PROXMOX not configured)",
            )
        check_scenario_in_db(client, args.scenario, report)
        check_metrics_live(client, report)

    check_prometheus_scrape(report)
    check_grafana_dashboard(report)

    report.print_summary()
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
