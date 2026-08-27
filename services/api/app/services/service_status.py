"""Service-status aggregation for the Config tab's deployment-status panel.

Read-only snapshot of the runtime environment the API is running in:

  * PVE probe         -- wraps admin_svc.probe_pve() so the panel can
                          share the same error shape as the other probes
                          on the Config tab.
  * wg-easy container -- best-effort TCP probe of :51820/udp on the
                          docker bridge network. wg-easy's healthcheck
                          already probes this port; if we can reach it
                          the container is up. Failures are reported as
                          "unreachable" (string), not raised.
  * WireGuard env     -- reads WG_HOST, WG_DEFAULT_DNS, DIVIDE_WG_PEER_SECRET
                          from os.environ. The secret is reported only as
                          "<set>" / "<unset>" so we never leak it.
  * API disk          -- shutil.disk_usage on /app (the overlay mount).
                          We expose used/total GB so operators can spot
                          an audit-log or drill-template runaway.
  * Audit-log recency -- query the most recent audit row's created_at;
                          "stale" if older than 24h, "fresh" otherwise.

Designed to fail-soft: every probe is wrapped so a single misbehaving
subsystem never tanks the whole panel. The endpoint is also cheap to
call (one PVE probe + one DB count + one env read) so the ConfigCard
can poll it on every Refresh.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.services import admin as admin_svc

log = logging.getLogger(__name__)


# wg-easy listens on 51820/udp. The container is on the divide-net
# docker network, so reaching the gateway OR a peer should tell us
# it's alive. We use a non-blocking UDP "ping" (send 0 bytes, accept
# timeout) -- this is intentionally best-effort and never raises.
_WG_PORT = 51820
_WG_PROBE_TIMEOUT_S = 1.0


def _probe_wg_easy() -> dict[str, Any]:
    """Best-effort UDP probe of the wg-easy container."""
    target = "wg-easy"
    try:
        socket.gethostbyname(target)
    except socket.gaierror:
        target = "127.0.0.1"

    try:
        with socket.create_connection(
            (target, _WG_PORT), timeout=_WG_PROBE_TIMEOUT_S
        ):
            return {"state": "up", "target": f"{target}:{_WG_PORT}/tcp"}
    except OSError as e:
        return {
            "state": "unreachable",
            "target": f"{target}:{_WG_PORT}/tcp",
            "error": str(e),
        }


def _wg_env_summary() -> dict[str, Any]:
    """WG_HOST + secret-presence summary. Never returns the secret."""
    host = os.environ.get("WG_HOST", "").strip()
    secret_set = bool(os.environ.get("DIVIDE_WG_PEER_SECRET", "").strip())
    dns = os.environ.get("WG_DEFAULT_DNS", "").strip()
    return {
        "wg_host": host or None,
        "wg_default_dns": dns or None,
        "peer_secret_set": secret_set,
        "ready": bool(host and secret_set),
    }


def _disk_summary(path: str = "/app") -> dict[str, Any]:
    try:
        u = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(u.total / (1024 ** 3), 2),
            "used_gb": round(u.used / (1024 ** 3), 2),
            "free_gb": round(u.free / (1024 ** 3), 2),
            "percent_used": round(100 * u.used / u.total, 1) if u.total else 0,
        }
    except OSError as e:
        return {"path": path, "error": str(e)}


async def _audit_recency(db: AsyncSession) -> dict[str, Any]:
    """When did the most recent audit row land? Used to detect
    'silent' deployments (no runs, no admin actions, no PVE calls).
    """
    try:
        row = (
            await db.execute(
                select(func.max(AuditLog.at))
            )
        ).scalar_one_or_none()
        if row is None:
            return {"latest": None, "state": "empty"}
        now = datetime.now(timezone.utc)
        age = now - row
        state = (
            "fresh"
            if age < timedelta(hours=24)
            else "stale"
        )
        return {
            "latest": row.isoformat(),
            "age_hours": round(age.total_seconds() / 3600, 1),
            "state": state,
        }
    except Exception as e:  # pragma: no cover -- defensive
        log.warning("audit recency probe failed: %s", e)
        return {"latest": None, "state": "unknown"}


async def get_service_status(db: AsyncSession) -> dict[str, Any]:
    """Top-level aggregator for GET /api/v1/admin/service-status.

    Every probe is wrapped; partial failures are surfaced in the
    response but never block the rest.
    """
    pve: dict[str, Any] = {}
    try:
        result = admin_svc.probe_pve()
        pve = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        pve_ok = bool(pve.get("reachable"))
    except Exception as e:  # pragma: no cover -- defensive
        pve = {"reachable": False, "error": str(e)}
        pve_ok = False

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "pve": {
            "reachable": pve.get("reachable", False),
            "version": pve.get("version"),
            "error": pve.get("error"),
        },
        "wg_easy": _probe_wg_easy(),
        "wireguard": _wg_env_summary(),
        "disk": _disk_summary(),
        "audit": await _audit_recency(db),
        "all_ok": pve_ok,
    }
