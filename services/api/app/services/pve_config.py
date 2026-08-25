"""Runtime PVE configuration store (DB singleton).

Day-1 web setup: this module lets the onboarding wizard collect PVE
credentials in the browser and store them in the database instead of
requiring the operator to edit ``deploy/.env`` and restart the API
container. The ``services/proxmox.py`` layer reads from this module
first, falling back to ``PROXMOX_*`` env vars if the DB has no row.

Precedence (see ``services/proxmox.py:_resolve_pve_config``):

    DB row in ``pve_config``  >  env vars

Both can coexist -- env is the bootstrap fallback so a brand-new stack
boots with reasonable defaults if the operator hasn't completed the
wizard yet.

The store is intentionally minimal: one upsert, one read, one delete.
We don't need pagination, soft-delete, or history because this is
operator-only configuration, not a record-of-truth.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PveConfig


# Singleton id. Same convention as the rest of div:ide's singleton
# tables: ``id`` is hard-coded to 1 and never reused.
_SINGLETON_ID = 1


class PveConfigError(ValueError):
    """Raised when an upsert input is malformed.

    The router maps this to HTTP 400 -- validation failures shouldn't
    reach Postgres. ``PveConfigProbeError`` (in routers/admin.py) maps
    to 502 because it indicates PVE rejected the credentials.
    """


async def get_config(db: AsyncSession) -> PveConfig | None:
    """Return the active PveConfig row, or None if unset.

    Caller is responsible for falling back to env vars when this
    returns None. We deliberately don't merge DB + env here -- that
    would muddy the precedence contract and confuse the wizard's
    "which source is in use?" banner.
    """
    row = await db.get(PveConfig, _SINGLETON_ID)
    return row


async def upsert_config(
    db: AsyncSession,
    *,
    host: str,
    port: int,
    user: str,
    token_id: str,
    token_secret: str,
    verify_ssl: bool,
    node: str | None,
    updated_by: str | None,
) -> PveConfig:
    """Write (or replace) the singleton row.

    The function never refuses to overwrite an existing row -- the
    operator's intent with ``POST /admin/pve-config`` is "make this
    the active config", and rejecting an overwrite would force them
    through a DELETE + POST dance for no real benefit.

    Raises ``PveConfigError`` if any required field is blank. We do
    this here (not just at the Pydantic boundary) because the
    router's error-mapping is clearer when the service raises a
    single canonical exception type.
    """
    if not (host or "").strip():
        raise PveConfigError("host is required")
    if not (user or "").strip():
        raise PveConfigError("user is required")
    if not (token_id or "").strip():
        raise PveConfigError("token_id is required")
    if not (token_secret or "").strip():
        raise PveConfigError("token_secret is required")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise PveConfigError(f"port must be 1..65535, got {port!r}")

    row = await db.get(PveConfig, _SINGLETON_ID)
    if row is None:
        row = PveConfig(
            id=_SINGLETON_ID,
            host=host.strip(),
            port=port,
            user=user.strip(),
            token_id=token_id.strip(),
            token_secret=token_secret,
            verify_ssl=bool(verify_ssl),
            node=(node or "").strip() or None,
            updated_by=updated_by,
        )
        db.add(row)
    else:
        # Update every field. If the operator leaves a field blank in
        # the wizard form, that's a bug in the wizard -- we already
        # validated it above, so we know they're populated.
        row.host = host.strip()
        row.port = port
        row.user = user.strip()
        row.token_id = token_id.strip()
        row.token_secret = token_secret
        row.verify_ssl = bool(verify_ssl)
        row.node = (node or "").strip() or None
        row.updated_by = updated_by

    await db.commit()
    await db.refresh(row)
    return row


async def delete_config(db: AsyncSession) -> bool:
    """Drop the singleton row, if present. Returns True if a row was deleted.

    After a delete, ``services/proxmox.py`` falls back to env vars.
    The wizard re-mounts the PveCredentialsStep in this state.
    """
    row = await db.get(PveConfig, _SINGLETON_ID)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


def env_source_dict() -> dict[str, Any]:
    """Return a public-shape dict representing the env-var fallback.

    Used by ``GET /api/v1/admin/pve-config`` when the DB has no row.
    Token secret is empty (we don't know it -- the env value would be
    a SecretStr), and ``source`` is ``"env"`` so the wizard can render
    "Configuration via env vars (deploy/.env)" rather than pretending
    the DB has it.
    """
    from app.core.config import settings

    cfg = settings.proxmox
    return {
        "source": "env",
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "token_id": cfg.token_id,
        "token_secret": "***" if cfg.token_secret else "",
        "verify_ssl": cfg.verify_ssl,
        "node": cfg.node,
        "updated_at": None,
        "updated_by": None,
    }


async def probe_config_with_db(db: AsyncSession) -> tuple[bool, str | None]:
    """Verify the DB row's credentials against PVE.

    Returns ``(ok, error_message)``. The caller (``POST /admin/pve-config``)
    commits only if ``ok``; this lets the operator learn about typos
    (wrong token name, wrong user, wrong host) before persisting.

    We import the proxmox layer lazily so a missing pve_config doesn't
    pull in proxmoxer at import time (Phase 0 -- the API boots without
    PVE creds).
    """
    from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError, get_version

    row = await get_config(db)
    if row is None:
        return False, "no pve_config row to probe"
    try:
        await get_version()
    except ProxmoxNotConfiguredError as e:
        return False, f"config incomplete: {e}"
    except ProxmoxAPIError as e:
        # Most common cause: 401 (token wrong), 403 (token right but
        # user lacks privileges), or connect error (host unreachable).
        # We surface the proxmoxer message verbatim -- it's already
        # operator-friendly.
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"unexpected probe error: {e}"
    return True, None
