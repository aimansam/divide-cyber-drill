"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging
from app.routers import drills, health, proxmox, scenarios
from app.services.scenario_sync import sync_files

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("divide_api.start", version=__version__, env=settings.env)

    if settings.sync_on_startup:
        try:
            from app.db.session import get_sessionmaker

            paths = [Path(settings.scenarios_dir), *(
                Path(p) for p in settings.extra_scenarios_dirs
            )]
            sm = get_sessionmaker()
            async with sm() as session:
                report = await sync_files(session, paths)
                log.info(
                    "divide_api.scenario_sync",
                    created=len(report.created),
                    updated=len(report.updated),
                    unchanged=len(report.unchanged),
                    skipped=len(report.skipped),
                    archived=len(report.archived),
                )
                if report.skipped:
                    log.warning(
                        "divide_api.scenario_sync.skipped",
                        skipped=[
                            {"path": str(s.source_path), "error": s.error}
                            for s in report.skipped
                        ],
                    )
                # Expose the report for /readyz / health.
                app.state.last_sync = report
        except Exception as exc:  # pragma: no cover - best-effort
            log.error("divide_api.scenario_sync.failed", error=str(exc))
            app.state.last_sync = None

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
