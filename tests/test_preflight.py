"""Tests for tools/preflight.py (no live calls -- uses httpx MockTransport).

We don't hit the real API / Prometheus / Grafana -- we use httpx's
MockTransport to fake each endpoint and assert the report structure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx


def _load_module():
    if "preflight" in sys.modules:
        del sys.modules["preflight"]
    spec = importlib.util.spec_from_file_location(
        "preflight",
        Path(__file__).resolve().parent.parent / "tools" / "preflight.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # CRITICAL: register in sys.modules BEFORE exec_module so @dataclass
    # can find the module via sys.modules.get(cls.__module__).
    sys.modules["preflight"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_with_handlers(handlers, monkeypatch, argv=()):
    """Run preflight.main() with the given URL -> handler mapping."""
    mod = _load_module()

    def _route(request):
        for prefix, handler in handlers.items():
            if str(request.url).startswith(prefix):
                return handler(request)
        return httpx.Response(404, json={"detail": "no handler"})

    transport = httpx.MockTransport(_route)
    original_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)
    monkeypatch.setattr(sys, "argv", ["preflight.py", *argv])
    return mod.main()


def _ok_health(r):
    return httpx.Response(200, json={"status": "ok", "env": "dev", "version": "0.1.0"})


def _prox_ok(r):
    return httpx.Response(200, json={"ok": True, "version": "9.1.7"})


def _nodes(r):
    return httpx.Response(200, json={"items": [{"node": "pve"}]})


def _scenarios_ok(r):
    return httpx.Response(
        200,
        json={
            "items": [
                {"id": 3, "name": "first-live-drill", "archived_at": None},
                {"id": 1, "name": "lateral-movement-baseline", "archived_at": None},
            ]
        },
    )


def _metrics(r):
    return httpx.Response(
        200,
        text="# HELP divide_runs_total x\n# TYPE divide_runs_total counter\n",
    )


def _prom_targets_up(r):
    return httpx.Response(
        200,
        json={
            "data": {
                "activeTargets": [
                    {
                        "labels": {"job": "divide-api"},
                        "scrapeUrl": "http://api:8000/metrics",
                        "health": "up",
                        "lastError": "",
                    }
                ]
            }
        },
    )


def _grafana_ok(r):
    return httpx.Response(
        200, json={"dashboard": {"title": "div:ide", "panels": [{}] * 6}}
    )


# --- happy path ---------------------------------------------------------


def test_all_checks_pass_when_everything_is_up(monkeypatch):
    handlers = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": _prox_ok,
        "http://localhost:8000/api/v1/proxmox/nodes": _nodes,
        "http://localhost:8000/api/v1/proxmox/acl": lambda r: httpx.Response(
            200,
            json={
                "items": [
                    {
                        "path": "/",
                        "ugid": "divide@pve@pam",
                        "roleid": "PVEVMAdmin",
                        "type": "user",
                        "propagate": 1,
                    }
                ],
                "total": 1,
            },
        ),
        "http://localhost:8000/api/v1/proxmox/templates": lambda r: httpx.Response(
            200, json={"items": [{"name": "tpl-debian-cloudinit", "vmid": 9000}]}
        ),
        "http://localhost:8000/api/v1/scenarios": _scenarios_ok,
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": _prom_targets_up,
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    assert _run_with_handlers(handlers, monkeypatch) == 0


# --- template missing --------------------------------------------------


def test_template_missing_prints_actionable_hint(monkeypatch, capsys):
    handlers = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": _prox_ok,
        "http://localhost:8000/api/v1/proxmox/nodes": _nodes,
        "http://localhost:8000/api/v1/proxmox/acl": lambda r: httpx.Response(
            200,
            json={
                "items": [
                    {
                        "path": "/",
                        "ugid": "divide@pve@pam",
                        "roleid": "PVEVMAdmin",
                        "type": "user",
                        "propagate": 1,
                    }
                ],
                "total": 1,
            },
        ),
        "http://localhost:8000/api/v1/proxmox/templates": lambda r: httpx.Response(
            200, json={"items": []}
        ),
        "http://localhost:8000/api/v1/scenarios": _scenarios_ok,
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": _prom_targets_up,
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Template" in out
    assert "make upload-template" in out
    assert "qemu-guest-agent" in out


# --- promox not configured ---------------------------------------------


def test_promox_not_configured_skips_pve_checks(monkeypatch, capsys):
    handlers = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": lambda r: httpx.Response(
            503, json={"detail": "Proxmox not configured"}
        ),
        "http://localhost:8000/api/v1/scenarios": lambda r: httpx.Response(
            200, json={"items": []}
        ),
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": lambda r: httpx.Response(
            200, json={"data": {"activeTargets": []}}
        ),
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "PROXMOX_* configured" in out
    assert "PVE nodes reachable" in out
    assert "skipped" in out


# --- prometheus target down --------------------------------------------


def test_prometheus_target_down_prints_error(monkeypatch, capsys):
    handlers = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": lambda r: httpx.Response(
            503, json={"detail": "x"}
        ),
        "http://localhost:8000/api/v1/scenarios": lambda r: httpx.Response(
            200, json={"items": []}
        ),
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": lambda r: httpx.Response(
            200,
            json={
                "data": {
                    "activeTargets": [
                        {
                            "labels": {"job": "divide-api"},
                            "scrapeUrl": "http://api:8000/metrics",
                            "health": "down",
                            "lastError": "connection refused",
                        }
                    ]
                }
            },
        ),
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Prometheus scraping divide-api" in out
    assert "down" in out


# --- arg parsing -------------------------------------------------------


def test_custom_scenario_and_template_args(monkeypatch):
    handlers = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": lambda r: httpx.Response(
            503, json={"detail": "x"}
        ),
        "http://localhost:8000/api/v1/scenarios": lambda r: httpx.Response(
            200, json={"items": []}
        ),
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": lambda r: httpx.Response(
            200, json={"data": {"activeTargets": []}}
        ),
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    rc = _run_with_handlers(
        handlers, monkeypatch, argv=["--scenario", "phish-to-ransom", "--template", "tpl-ubuntu-2204"]
    )
    # Just confirms we ran with the args -- not everything passes.
    assert rc == 1


# --- ACL check ------------------------------------------------------------


def _acl_handlers(acl_response=None, acl_status=200, **kwargs):
    """Build a handlers dict for ACL-related tests.

    acl_response is the body returned by /api/v1/proxmox/acl.
    acl_status is the HTTP status.
    Any extra kwargs are added as additional handlers.
    """
    def acl(req):
        return httpx.Response(acl_status, json=acl_response or {})

    base = {
        "http://localhost:8000/healthz": _ok_health,
        "http://localhost:8000/api/v1/proxmox/health": _prox_ok,
        "http://localhost:8000/api/v1/proxmox/nodes": _nodes,
        "http://localhost:8000/api/v1/proxmox/acl": acl,
        "http://localhost:8000/api/v1/proxmox/templates": lambda r: httpx.Response(
            200, json={"items": [{"name": "tpl-debian-cloudinit", "vmid": 9000}]}
        ),
        "http://localhost:8000/api/v1/scenarios": _scenarios_ok,
        "http://localhost:8000/metrics": _metrics,
        "http://localhost:9090/api/v1/targets": _prom_targets_up,
        "http://localhost:3000/api/dashboards/uid/divide-drill-platform": _grafana_ok,
    }
    base.update(kwargs)
    return base


def test_acl_direct_vm_grant_passes(monkeypatch):
    """ACL with direct /v2/vm + PVEVMAdmin → PASS."""
    handlers = _acl_handlers(
        acl_response={
            "items": [
                {
                    "path": "/v2/vm",
                    "ugid": "divide@pve@pam",
                    "roleid": "PVEVMAdmin",
                    "type": "user",
                    "propagate": 1,
                }
            ],
            "total": 1,
        }
    )
    assert _run_with_handlers(handlers, monkeypatch) == 0


def test_acl_propagated_root_grant_passes(monkeypatch):
    """PVEVMAdmin on / with propagate=1 → PASS (inherits /v2/vm)."""
    handlers = _acl_handlers(
        acl_response={
            "items": [
                {
                    "path": "/",
                    "ugid": "divide@pve@pam",
                    "roleid": "PVEVMAdmin",
                    "type": "user",
                    "propagate": 1,
                }
            ],
            "total": 1,
        }
    )
    assert _run_with_handlers(handlers, monkeypatch) == 0


def test_acl_pveadmin_root_passes(monkeypatch):
    """PVEAdmin on / is a superset of PVEVMAdmin → PASS."""
    handlers = _acl_handlers(
        acl_response={
            "items": [
                {
                    "path": "/",
                    "ugid": "divide@pve@pam",
                    "roleid": "PVEAdmin",
                    "type": "user",
                    "propagate": 1,
                }
            ],
            "total": 1,
        }
    )
    assert _run_with_handlers(handlers, monkeypatch) == 0


def test_acl_only_pveauditor_fails(monkeypatch, capsys):
    """PVEAuditor on / is read-only → ACL check FAILs with hint."""
    handlers = _acl_handlers(
        acl_response={
            "items": [
                {
                    "path": "/",
                    "ugid": "divide@pve@pam",
                    "roleid": "PVEAuditor",
                    "type": "user",
                    "propagate": 1,
                }
            ],
            "total": 1,
        }
    )
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ACL grants PVEVMAdmin" in out
    assert "pveum acl modify" in out


def test_acl_empty_response_fails_with_cache_hint(monkeypatch, capsys):
    """Empty ACL response (stale pveproxy cache) → FAIL with restart hint."""
    handlers = _acl_handlers(acl_response={"items": [], "total": 0})
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ACL grants PVEVMAdmin" in out
    assert "pveproxy" in out


def test_acl_502_fails_with_pveum_hint(monkeypatch, capsys):
    """If the ACL endpoint itself errors, check should still fail cleanly."""
    def bad_acl(req):
        return httpx.Response(502, text="upstream error")

    handlers = _acl_handlers()
    handlers["http://localhost:8000/api/v1/proxmox/acl"] = bad_acl
    rc = _run_with_handlers(handlers, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ACL grants PVEVMAdmin" in out
