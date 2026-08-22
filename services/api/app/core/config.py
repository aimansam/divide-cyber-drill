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
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Proxmox
    proxmox: ProxmoxSettings = Field(default_factory=ProxmoxSettings)


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
