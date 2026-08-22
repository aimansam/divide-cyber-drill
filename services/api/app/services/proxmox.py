"""Proxmox API client wrapper.

Phase 0: this module is lazy-instantiated so the API container boots even
without Proxmox credentials. Real Proxmox integration is gated until we get
explicit user sign-off (see docs/PLAN.md §13 and the staging plan).

Read-only endpoints land first (Stage 2). Write endpoints (clone/start/stop)
require token promotion to PVEVMAdmin and are scheduled for Stage 3+.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from proxmoxer import ProxmoxAPI

from app.core.config import settings


class ProxmoxNotConfiguredError(RuntimeError):
    """Raised when Proxmox credentials are missing or incomplete."""


class ProxmoxAPIError(RuntimeError):
    """Raised when a Proxmox API call fails (network, auth, parse, etc.)."""


def _validate_config() -> tuple[str, str, str]:
    cfg = settings.proxmox
    raw_host = (cfg.host or "").strip()
    if not raw_host:
        raise ProxmoxNotConfiguredError("PROXMOX_HOST is not set")
    # proxmoxer wants host without scheme — scheme is controlled by `backend`.
    host = raw_host
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.rstrip("/")
    if not (cfg.token_id or "").strip() or not cfg.token_secret:
        raise ProxmoxNotConfiguredError(
            "PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET must be set"
        )
    # PROXMOX_TOKEN_ID is the full "user!tokenname" string (e.g. "divide@pve!drill-token"),
    # NOT just the token name. proxmoxer wants (user, token_name) separately:
    #   token_name = everything after the first "!" in token_id
    token_full = (cfg.token_id or "").strip()
    token_name = token_full.split("!", 1)[1] if "!" in token_full else token_full
    return host, cfg.user, token_name, cfg.token_secret.get_secret_value()


@lru_cache
def get_proxmox_client() -> ProxmoxAPI:
    """Return a cached ProxmoxAPI instance. Lazy — only validates on first call."""
    host, user, token_name, token_secret = _validate_config()
    return ProxmoxAPI(
        host=host,
        port=settings.proxmox.port,
        user=user,
        token_name=token_name,
        token_value=token_secret,
        verify_ssl=settings.proxmox.verify_ssl,
        backend="https",
    )


# ---------------------------------------------------------------------------
# Read-only helpers (Stage 2)
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_SECONDS = 300


def _cache_get(key: str) -> Any | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> Any:
    _CACHE[key] = (time.monotonic(), value)
    return value


def _call(key: str, fn):
    """Run fn() with TTL caching; surface proxmoxer errors as ProxmoxAPIError."""
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        result = fn()
    except ProxmoxNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001
        # proxmoxer raises its own exceptions (ResourceException, etc.) — wrap
        # them as ProxmoxAPIError so callers have a single error type to catch.
        raise ProxmoxAPIError(f"{type(exc).__name__}: {exc}") from exc
    return _cache_set(key, result)


def clear_cache() -> None:
    """Test helper — drop the TTL cache."""
    _CACHE.clear()


def get_version() -> dict:
    """PVE version info (release, version, repoid)."""
    return _call("version", lambda: get_proxmox_client().version.get())


def list_nodes() -> list[dict]:
    """List cluster nodes with status, level, and best-effort IP."""
    raw = _call("nodes", lambda: get_proxmox_client().nodes.get())
    out: list[dict] = []
    for n in raw:
        out.append(
            {
                "node": n.get("node"),
                "status": n.get("status"),
                "level": n.get("level"),
                "ip": n.get("ip") or n.get("localip") or None,
                "cpu_pct": _float_or_none(n.get("cpu")),
                "mem_total_bytes": _int_or_none(n.get("maxmem")),
                "mem_used_bytes": _int_or_none(n.get("mem")),
            }
        )
    return out


def list_storage() -> list[dict]:
    """List storage pools (free/total/content type)."""
    raw = _call("storage", lambda: get_proxmox_client().storage.get())
    out: list[dict] = []
    for s in raw:
        out.append(
            {
                "storage": s.get("storage"),
                "type": s.get("type"),
                "content": (s.get("content") or "").split(",") if s.get("content") else [],
                "free_bytes": _int_or_none(s.get("avail")),
                "total_bytes": _int_or_none(s.get("total")),
                "active": bool(s.get("active", True)),
            }
        )
    return out


def list_templates(node: str | None = None) -> list[dict]:
    """List VM templates. If node is given, only that node's templates."""
    cfg = settings.proxmox
    target = node or (cfg.node or "").strip() or None

    def _fetch():
        client = get_proxmox_client()
        if target:
            vms = client.nodes(target).qemu.get()
        else:
            vms = []
            for n in client.nodes.get():
                try:
                    vms.extend(client.nodes(n["node"]).qemu.get())
                except Exception:  # noqa: BLE001
                    # Skip unreachable nodes — partial result is still useful
                    continue
        return vms

    raw = _call(f"templates:{target or 'all'}", _fetch)
    out: list[dict] = []
    for v in raw:
        # proxmoxer returns template=1 for templates, 0 otherwise. Be lenient
        # about missing keys (some non-template VMs don't include the field).
        if not v.get("template", 0):
            continue
        out.append(
            {
                "vmid": v.get("vmid"),
                "name": v.get("name") or f"vmid-{v.get('vmid')}",
                "node": v.get("node") or target,
                "status": v.get("status"),
            }
        )
    return out


def list_acl() -> list[dict]:
    """List the full access control table — every (path, user/group/token, role)
    triple that grants permissions on the cluster.

    Note: with API-token auth, the token is treated as a separate principal
    (``divide@pve@pam!drill-token``). For our flow the token inherits the
    user's roles; we don't grant roles on the token directly. So the check
    for write-permissions is really: does the *user* ``divide@pve@pam``
    have ``PVEVMAdmin`` (or broader) on ``/v2/vm`` or ``/`` with propagate?

    Each entry is a dict with keys: ``path``, ``ugid``, ``roleid``, ``type``,
    ``propagate``.
    """
    return _call("acl", lambda: get_proxmox_client().access.acl.get())


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
