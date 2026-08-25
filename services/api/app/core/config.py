"""Application settings via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxmoxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROXMOX_", extra="ignore")

    host: str | None = None
    port: int = 8006
    user: str = "divide@pve"
    token_id: str | None = None
    token_secret: SecretStr | None = None
    verify_ssl: bool = True
    node: str | None = None  # e.g. "pve" — used when node cannot be auto-detected


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DIVIDE_",
        extra="ignore",
    )

    env: Literal["dev", "staging", "production"] = "dev"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Database
    db_url: str = "postgresql+asyncpg://divide:divide@postgres:5432/divide"
    db_echo: bool = False

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "divide"
    minio_secret_key: SecretStr = SecretStr("dividedividedivide")
    minio_bucket: str = "divide-artifacts"
    minio_secure: bool = False

    # CORS
    # Comma-separated list of allowed origins. The browser sends an Origin
    # header on every cross-origin request, and the CORS middleware only
    # echoes it back if it appears verbatim in ``allow_origins``. Wildcards
    # are deliberately not supported in production (CORSMiddleware treats
    # ``allow_origins=["*"]`` as not-safe-with-credentials, which is the
    # default posture we want — set this list explicitly to open up).
    #
    # Default: a localhost origin for the setup wizard's dev loop. In any
    # deployment, override with ``DIVIDE_CORS_ALLOW_ORIGINS="https://
    # drill.example.com,https://ops.example.com"``.
    #
    # Implementation note: the model field is ``cors_allow_origins_raw`` so
    # pydantic-settings doesn't auto-generate ``DIVIDE_CORS_ALLOW_ORIGINS``
    # (which would be ambiguous — it would expect a list, not a string). The
    # ``validation_alias`` below pins the friendly env name to this field.
    cors_allow_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias="DIVIDE_CORS_ALLOW_ORIGINS",
    )

    @property
    def cors_allow_origins(self) -> list[str]:
        """Parse the comma-separated env var into a list of origins.

        Whitespace around each entry is stripped; empty entries are
        dropped. The result is the list FastAPI's ``CORSMiddleware``
        expects. Returning a fresh list per call (rather than caching on
        the ``Settings`` instance) keeps the property picklable via the
        ``lru_cache`` proxy and lets us re-read env in tests.
        """
        parts = (s.strip() for s in self.cors_allow_origins_raw.split(","))
        return [p for p in parts if p]

    # Proxmox
    proxmox: ProxmoxSettings = Field(default_factory=ProxmoxSettings)

    # Scenario catalog
    scenarios_dir: str = "/workdir/examples/scenarios"
    sync_on_startup: bool = True
    extra_scenarios_dirs: list[str] = Field(default_factory=list)

    # HMAC secret for the X-Divide-Token auth. If unset, dev falls
    # back to a derivation of PROXMOX_TOKEN_SECRET (with a warning);
    # prod should always set this explicitly. The fallback is so a
    # freshly cloned repo can run `divide issue-token` without an
    # extra env var.
    divide_token_secret: SecretStr | None = None

    # Setup wizard portal (vanilla HTML+JS). Mounted at /portal/ by main.py.
    # Defaults to the bundled copy; override for development to point at
    # the live source tree.
    portal_dir: str = "/app/portal"

    # Drill lifecycle (L2 2.8) — auto-timeout runs that stay RUNNING for
    # longer than this many minutes. The watchdog asyncio task is
    # scheduled by ``Runner._maybe_schedule_watchdog`` after a run enters
    # RUNNING; it sleeps `drill_timeout_min * 60` then flips the row to
    # TIMEOUT, best-effort tears down assets, and writes RUN_TIMEOUT audit.
    # Set to a non-positive value to disable (e.g. for soak testing).
    drill_timeout_min: int = 30
    # Disable via env when operators want to keep a run alive past the
    # timeout (e.g., a 4-hour red-team exercise). In dev, set to 0 to
    # defeat the watchdog entirely. The toggle is a bool; the timeout
    # only fires if both ``drill_timeout_enabled=True`` AND
    # ``drill_timeout_min > 0``.
    drill_timeout_enabled: bool = True

    # F3-prep credential login. Lifetime of the HMAC token minted by
    # POST /api/v1/auth/login, in seconds. Default 8h covers a working
    # day; override for shorter demos. Clamped to a positive int at the
    # router (zero / negative falls back to default).
    login_token_ttl_s: int = 8 * 3600

    # F3-prep bootstrap admin. On API startup, if BOTH vars are set AND
    # no admin user exists, a row is created with role="admin". Used to
    # seed the very first admin without an SSH session. Both vars are
    # secrets: ``bootstrap_admin_password`` is a SecretStr so it's
    # never echoed in logs. After the first admin exists the env vars
    # are no-ops; remove them from the env file to reduce blast radius.
    bootstrap_admin_sub: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # WireGuard VPN settings.
    #
    # DIVIDE_WG_HOST — the public IP/hostname trainees use in their
    #   [Peer] Endpoint line. Must be reachable from the internet (or
    #   the LAN for internal-only deployments). Defaults to empty which
    #   makes the config say "Endpoint = <your-server-ip>:51820" as a
    #   reminder to set it.
    #
    # DIVIDE_WG_PEER_SECRET — a random 32+ char string used to
    #   deterministically derive each user's keypair. Change this to
    #   invalidate all existing peer configs (forces re-download).
    #   Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
    #
    # DIVIDE_WG_SUBNET — the VPN address pool. Clients get addresses
    #   from this pool; the server takes .1. Default: 10.13.37.0/24.
    #
    # DIVIDE_WG_ALLOWED_IPS — what the client routes over VPN. Default
    #   routes only the drill subnet (10.10.0.0/16) so trainees keep
    #   normal internet access and only drill VM traffic goes through VPN.
    #
    # DIVIDE_WG_DNS — DNS server pushed to the client. Default: 1.1.1.1.
    wg_host: str = ""
    wg_peer_secret: SecretStr = SecretStr("change-me-generate-with-secrets-token-hex-32")
    wg_subnet: str = "10.13.37.0/24"
    wg_allowed_ips: str = "10.10.0.0/16, 10.13.37.0/24"
    wg_dns: str = "1.1.1.1"
    wg_port: int = 51820


@lru_cache
def get_settings() -> Settings:
    return Settings()


class _SettingsProxy:
    """Proxy that always delegates to `get_settings()`, so env-var changes
    (e.g. in tests) are picked up without an import-time freeze.

    Usage in code stays the same as a module-level `settings` instance:
        from app.core.config import settings
        host = settings.proxmox.host
    """

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()
