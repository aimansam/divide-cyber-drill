"""Liveness, readiness, and metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app import __version__
from app.observability import render_latest

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    env: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Return 200 if the process is alive. Used by Docker / Traefik."""
    from app.core.config import settings

    return HealthResponse(status="ok", version=__version__, env=settings.env)


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz() -> ReadinessResponse:
    """Return 200 if all critical dependencies are reachable."""
    from app.core.config import settings

    checks: dict[str, str] = {}

    # DB check (lazy import — keeps /healthz fast)
    try:
        from app.services.db import ping_db

        await ping_db()
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"fail: {exc.__class__.__name__}"

    try:
        from app.services.cache import ping_redis

        await ping_redis()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"fail: {exc.__class__.__name__}"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return ReadinessResponse(status=status, checks=checks)


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=Response,
)
async def metrics() -> Response:
    """Prometheus exposition format. Scrape with /metrics every 15s.

    No auth — the assumption is the API is reachable only via the
    internal Docker network or behind Traefik with basic auth. If you
    expose /metrics publicly, add an ACL on the route.
    """
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
