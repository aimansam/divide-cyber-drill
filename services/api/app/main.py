"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging
from app.observability.middleware import PrometheusMiddleware
from app.routers import admin, auth, drills, health, me, proxmox, reports, scenarios
from app.services.scenario_sync import sync_files

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    log.info("divide_api.start", version=__version__, env=settings.env)

    if settings.sync_on_startup:
        # F3-prep: bootstrap admin from env vars. Idempotent — only
        # fires if the env vars are set AND no admin exists yet. We
        # log loudly either way so operators can confirm intent.
        try:
            from app.db.session import get_sessionmaker
            from app.services.users import (
                DuplicateSubError,
                UserStoreError,
                create_user,
                get_by_sub,
            )

            admin_sub = settings.bootstrap_admin_sub
            admin_pw_secret = settings.bootstrap_admin_password
            if admin_sub and admin_pw_secret is not None:
                sm_boot = get_sessionmaker()
                async with sm_boot() as boot_session:
                    existing = await get_by_sub(boot_session, admin_sub)
                    if existing is None:
                        try:
                            await create_user(
                                boot_session,
                                sub=admin_sub,
                                password=admin_pw_secret.get_secret_value(),
                                role="admin",
                            )
                            await boot_session.commit()
                            log.info(
                                "divide_api.bootstrap_admin.created",
                                sub=admin_sub,
                            )
                        except DuplicateSubError:
                            await boot_session.rollback()
                            log.info(
                                "divide_api.bootstrap_admin.race",
                                sub=admin_sub,
                            )
                        except UserStoreError as exc:
                            await boot_session.rollback()
                            log.error(
                                "divide_api.bootstrap_admin.failed",
                                sub=admin_sub,
                                error=str(exc),
                            )
                    else:
                        log.info(
                            "divide_api.bootstrap_admin.skipped_exists",
                            sub=admin_sub,
                        )
            else:
                log.info("divide_api.bootstrap_admin.skipped_no_env")
        except Exception as exc:  # pragma: no cover - best-effort
            log.error("divide_api.bootstrap_admin.crashed", error=str(exc))

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

    # Metrics middleware installed LAST (outermost) so it sees the
    # final status code after CORS and other middleware have run.
    app.add_middleware(PrometheusMiddleware)

    app.include_router(health.router, prefix="", tags=["health"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(me.router, prefix="/api/v1/me", tags=["me"])
    app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
    app.include_router(drills.router, prefix="/api/v1/drills", tags=["drills"])
    app.include_router(reports.router, prefix="/api/v1/drills", tags=["reports"])
    app.include_router(proxmox.router, prefix="/api/v1/proxmox", tags=["proxmox"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])

    # F4 noVNC: register the WS proxy route directly on the app
    # because FastAPI router.include_router doesn't surface
    # WebSocket routes. The handler lives in
    # ``app.services.console_proxy`` and is wired to
    # ``/api/v1/drills/{run_id}/assets/{asset_id}/console/ws``.
    from fastapi import WebSocket  # noqa: F401  - used by ws_console
    from app.services.console_proxy import ws_console  # type: ignore
    app.add_api_websocket_route(
        "/api/v1/drills/{run_id}/assets/{asset_id}/console/ws",
        ws_console,
    )

    # Mount the React-based user portal at /portal/app/ FIRST. Starlette
    # resolves mounts by first match, so the more-specific subpath has
    # to be registered before the catch-all /portal mount below.
    #
    # The Vite source tree (services/portal/app/) has its own
    # index.html at the root that references /src/main.tsx — that's
    # only useful for `npm run dev`, not for production serving. We
    # serve `build/index.html` (the Vite-built artifact) here. Bind
    # mount in compose.yml guarantees a host-side rebuild propagates
    # without an image rebuild.
    portal_path = Path(settings.portal_dir)
    if portal_path.is_dir():
        app_build = portal_path / "app" / "build"
        if app_build.is_dir():
            app.mount(
                "/portal/app",
                StaticFiles(directory=str(app_build), html=True),
                name="portal_app",
            )
        else:
            log.warning(
                "divide_api.portal_app_build_skipped",
                build_dir=str(app_build),
                reason=(
                    "run `npm run build` in services/portal/app; "
                    "user portal not served"
                ),
            )

        # Setup wizard + operator test tool. Mounted last so the
        # /portal/app/ subpath above is matched first.
        app.mount(
            "/portal",
            StaticFiles(directory=str(portal_path), html=True),
            name="portal",
        )
    else:
        log.warning(
            "divide_api.portal_skipped",
            portal_dir=str(portal_path),
            reason="directory does not exist; admin endpoints still work via API",
        )

    return app


app = create_app()
