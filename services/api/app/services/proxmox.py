"""Proxmox API client wrapper.

Phase 0: this module is lazy-instantiated so the API container boots even
without Proxmox credentials. Real Proxmox integration is gated until we get
explicit user sign-off (see docs/PLAN.md §13 and the staging plan).
"""
from __future__ import annotations

from functools import lru_cache

from proxmoxer import ProxmoxAPI

from app.core.config import settings


class ProxmoxNotConfiguredError(RuntimeError):
    """Raised when Proxmox credentials are missing or incomplete."""


def _validate_config() -> tuple[str, str, str]:
    cfg = settings.proxmox
    host = (cfg.host or "").strip()
    if not host:
        raise ProxmoxNotConfiguredError("PROXMOX_HOST is not set")
    if not (cfg.token_id or "").strip() or not cfg.token_secret:
        raise ProxmoxNotConfiguredError(
            "PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET must be set"
        )
    return host, f"{cfg.user}!{cfg.token_id}", cfg.token_secret.get_secret_value()


@lru_cache
def get_proxmox_client() -> ProxmoxAPI:
    """Return a cached ProxmoxAPI instance. Lazy — only validates on first call."""
    host, token_id, token_secret = _validate_config()
    return ProxmoxAPI(
        host=host,
        port=settings.proxmox.port,
        user=settings.proxmox.user,
        token_name=token_id.split("!", 1)[1],
        token_value=token_secret,
        verify_ssl=settings.proxmox.verify_ssl,
        backend="https",
    )
