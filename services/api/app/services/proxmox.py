"""Proxmox API client wrapper.

Phase 0: this module is lazy-instantiated so the API container boots even
without Proxmox credentials. Real Proxmox integration is gated until we get
explicit user sign-off (see docs/PLAN.md §13 and the staging plan).

Read-only endpoints land first (Stage 2). Write endpoints (clone/start/stop)
require token promotion to PVEVMAdmin and are scheduled for Stage 3+.

Resolution order (day-1 web setup, see ``services/pve_config.py``):

    1. ``pve_config`` row in DB    (set by ``POST /api/v1/admin/pve-config``)
    2. ``PROXMOX_*`` env vars      (bootstrap / dev fallback)

The DB layer is hydrated at app startup by ``hydrate_proxmox_from_db``
(see ``main.py:lifespan``); writes via ``POST /admin/pve-config`` call
``reload_proxmox_from_db`` to invalidate the local cache so the next
PVE call picks up the new credentials without a container restart.
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


# In-process overlay for the PVE config. Hydrated from the ``pve_config``
# DB row at startup and on every successful ``POST /admin/pve-config``.
# Stored as a dict (not the ORM object) so callers can use it without an
# open session. ``None`` means "no overlay, use env vars".
#
# This is intentionally simple. We don't need an LRU -- one row, one
# cache entry, refreshed at known points. Stale-cache risk is bounded
# by the explicit ``reload_proxmox_from_db`` call in the admin router.
_DB_OVERLAY: dict[str, Any] | None = None


def _validate_config() -> tuple[str, str, str]:
    """Resolve PVE creds from the DB overlay if present, else env.

    The DB overlay takes precedence: once an admin POSTs
    ``/api/v1/admin/pve-config``, the env-var fallback is dead until
    the operator DELETEs the row. This is intentional -- the wizard
    is the canonical setup path; env is only for the bootstrap case
    where the wizard hasn't been reached yet.
    """
    if _DB_OVERLAY is not None:
        host = (_DB_OVERLAY.get("host") or "").strip()
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.rstrip("/")
        token_full = (_DB_OVERLAY.get("token_id") or "").strip()
        token_name = token_full.split("!", 1)[1] if "!" in token_full else token_full
        user = (_DB_OVERLAY.get("user") or "").strip()
        secret = _DB_OVERLAY.get("token_secret") or ""
        if not host:
            raise ProxmoxNotConfiguredError("pve_config.host is empty")
        if not user or not token_name or not secret:
            raise ProxmoxNotConfiguredError(
                "pve_config.user, token_id, and token_secret are all required"
            )
        return host, user, token_name, secret

    # Fall back to env-var driven config. Kept exactly as before so
    # deployments that never adopted the wizard keep working.
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
    # Resolve verify_ssl + port + node from the same source as the
    # host/user/token (DB overlay first, env fallback). Previously this
    # hard-coded ``settings.proxmox`` -- now we honor the overlay so
    # ``POST /admin/pve-config`` actually changes runtime behavior.
    if _DB_OVERLAY is not None:
        port = _DB_OVERLAY.get("port") or 8006
        verify_ssl = bool(_DB_OVERLAY.get("verify_ssl", False))
    else:
        port = settings.proxmox.port
        verify_ssl = settings.proxmox.verify_ssl
    return ProxmoxAPI(
        host=host,
        port=port,
        user=user,
        token_name=token_name,
        token_value=token_secret,
        verify_ssl=verify_ssl,
        backend="https",
    )


def get_configured_node() -> str | None:
    """Return the node name from the active source, or None.

    Used by runners when they can't auto-detect the node (e.g. when
    the API is configured for a single-node cluster). Same precedence
    rule as the rest of the file: DB overlay first, env fallback.
    """
    if _DB_OVERLAY is not None:
        return _DB_OVERLAY.get("node")
    return settings.proxmox.node


# ---------------------------------------------------------------------------
# Overlay lifecycle (called from main.py lifespan and admin router).
# ---------------------------------------------------------------------------


def set_db_overlay(overlay: dict[str, Any] | None) -> None:
    """Install (or clear) the in-memory PVE config overlay.

    Pass a dict like ``{"host": ..., "port": ..., "user": ..., ...}`` to
    activate DB-driven resolution. Pass ``None`` to revert to env vars.

    Also clears the ``get_proxmox_client`` LRU cache and the TTL cache
    so the next PVE call rebuilds from the new overlay. This is the
    single source of truth for "force a fresh connect" -- every code
    path that mutates the DB overlay goes through here.
    """
    global _DB_OVERLAY
    _DB_OVERLAY = overlay
    get_proxmox_client.cache_clear()  # type: ignore[attr-defined]
    clear_cache()


async def hydrate_proxmox_from_db() -> None:
    """Read the ``pve_config`` row and install it as the overlay.

    Called once at API startup. If the table doesn't exist yet (fresh
    install, pre-migration) or the row is missing (operator hasn't
    completed the wizard), this is a no-op -- env vars are the
    bootstrap fallback.

    We import the DB layer lazily to keep ``services/proxmox.py``
    import-safe (Phase 0 -- the API boots before Postgres is up).
    """
    try:
        from app.db.session import session_scope
        from app.services.pve_config import get_config
    except ImportError:
        return
    try:
        async with session_scope() as db:
            row = await get_config(db)
    except Exception:
        # Best-effort. If the DB is unreachable at boot, we still
        # want the API to come up; the wizard will retry on POST.
        return
    if row is None:
        set_db_overlay(None)
        return
    set_db_overlay(
        {
            "host": row.host,
            "port": row.port,
            "user": row.user,
            "token_id": row.token_id,
            "token_secret": row.token_secret,
            "verify_ssl": row.verify_ssl,
            "node": row.node,
        }
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

    IMPORTANT: this endpoint requires the ``Access.Audit`` privilege, which
    is NOT part of ``PVEVMAdmin``. A token scoped to PVEVMAdmin only will
    get an empty list back from PVE (not an error -- PVE silently returns
    ``[]`` for principals that lack Access.Audit). For permission-checking,
    prefer ``list_permissions()`` which every authenticated user can read
    for themselves.
    """
    return _call("acl", lambda: get_proxmox_client().access.acl.get())


def list_permissions() -> dict[str, dict[str, int]]:
    """List the privileges the current token inherits, grouped by path.

    Calls ``GET /access/permissions``, which every authenticated principal
    can call (no special privilege required). The result is a mapping of
    ``{path: {privilege: 1}}`` -- e.g.::

        {
            "/": {"VM.Allocate": 1, "VM.Clone": 1, ...},
            "/vms": {"VM.Allocate": 1, "VM.Clone": 1, ...},
            "/access": {...},
            ...
        }

    A path with propagate=1 in the underlying ACL appears under the root
    path (``/``) here, with every privilege the role grants listed. Use
    this instead of ``list_acl()`` when you want to verify *your token*
    has the privileges you need without exposing the full cluster ACL.
    """
    return _call(
        "permissions",
        lambda: get_proxmox_client().access.permissions.get(),
    )


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
