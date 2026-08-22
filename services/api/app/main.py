"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging
from app.routers import drills, health, proxmox, scenarios

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("divide_api.start", version=__version__, env=settings.env)
    yield
    log.info("divide_api.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="div:ide API",
        version=__version__,
        description="div:ide — Cyber Drill Platform control-plane API",
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="", tags=["health"])
    app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
    app.include_router(drills.router, prefix="/api/v1/drills", tags=["drills"])
    app.include_router(proxmox.router, prefix="/api/v1/proxmox", tags=["proxmox"])

    return app


app = create_app()
