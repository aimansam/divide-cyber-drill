"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import __version__
from app.core.config import settings
from app.core.logging import configure_logging
from app.db import models
from app.observability.middleware import PrometheusMiddleware
from app.routers import admin, audit, auth, debrief, drills, events, exercises, health, me, proxmox, reports, scenarios, templates
from app.services import orphan_cleanup as orphan_svc
from app.services.scenario_sync import sync_files
from app.runners.runner import build_runner

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
                # Q2 fix: warn loudly if no users exist and the operator
                # has not configured the bootstrap env vars. Without this
                # warning, a fresh install will silently come up with
                # zero users, the wizard will hang at the login screen,
                # and the operator has no signal that they need to set
                # DIVIDE_BOOTSTRAP_ADMIN_SUB + DIVIDE_BOOTSTRAP_ADMIN_PASSWORD.
                try:
                    from sqlalchemy import func, select

                    from app.db.models import User

                    sm_check = get_sessionmaker()
                    async with sm_check() as check_session:
                        user_count = (
                            await check_session.execute(
                                select(func.count()).select_from(User)
                            )
                        ).scalar_one()
                    if user_count == 0:
                        log.warning(
                            "divide_api.bootstrap_admin.missing_admin",
                            hint=(
                                "No users exist and DIVIDE_BOOTSTRAP_ADMIN_SUB "
                                "/ DIVIDE_BOOTSTRAP_ADMIN_PASSWORD are not set. "
                                "The wizard will render but no one can sign in. "
                                "Set both env vars in deploy/.env and restart the "
                                "API container to bootstrap the first admin."
                            ),
                        )
                except Exception as exc:  # pragma: no cover - best-effort
                    log.warning(
                        "divide_api.bootstrap_admin.missing_admin_check_failed",
                        error=str(exc),
                    )
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

    # Day-1 web setup: hydrate the in-memory PVE config overlay from
    # the ``pve_config`` DB row. If the row exists, this overrides the
    # ``PROXMOX_*`` env-var fallback for the lifetime of the process.
    # If it doesn't exist (operator hasn't reached the wizard yet),
    # env vars remain the source of truth -- this is the bootstrap path.
    #
    # Failures here are logged-and-swallowed: a DB that's briefly
    # unreachable at boot must not prevent the API from coming up.
    try:
        from app.services.proxmox import hydrate_proxmox_from_db

        await hydrate_proxmox_from_db()
        log.info("divide_api.pve_overlay.hydrated")
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning("divide_api.pve_overlay.hydrate_failed", error=str(exc))

    # Q22: orphan janitor background task. Off by default
    # (orphan_janitor_enabled=False). When on, periodically calls
    # the same cleanup_orphans() helper that backs POST
    # /api/v1/admin/assets/cleanup. Cancellable on shutdown.
    janitor_task = None
    if settings.orphan_janitor_enabled:
        from app.db.session import get_sessionmaker

        async def _janitor_loop() -> None:
            sm = get_sessionmaker()
            runner = build_runner()
            adapter = runner._adapter  # noqa: SLF001
            interval = settings.orphan_janitor_interval_min * 60
            grace = settings.orphan_janitor_grace_minutes
            log.info(
                "divide_api.orphan_janitor.started",
                interval_min=settings.orphan_janitor_interval_min,
                grace_minutes=grace,
            )
            import asyncio

            while True:
                try:
                    async with sm() as session:
                        result = await orphan_svc.cleanup_orphans(
                            session,
                            adapter,
                            actor="system:janitor",
                            grace_minutes=grace,
                        )
                    if result.destroyed or result.failed:
                        log.info(
                            "divide_api.orphan_janitor.tick",
                            scanned=result.scanned,
                            destroyed=result.destroyed,
                            failed=len(result.failed),
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "divide_api.orphan_janitor.error", error=str(exc)
                    )
                await asyncio.sleep(interval)

        import asyncio

        janitor_task = asyncio.create_task(_janitor_loop())

    # Fix: Watchdog recovery after API restart.
    # Reschedules watchdogs for any RUNNING drills so timeouts still fire
    # even if the API container restarted mid-drill.
    try:
        from app.db.session import get_sessionmaker
        from app.runners.runner import Runner

        sm_recovery = get_sessionmaker()
        async with sm_recovery() as recovery_session:
            rescheduled = await Runner.recover_watchdogs(recovery_session)
            if rescheduled > 0:
                log.info(
                    "divide_api.watchdog_recovery.completed",
                    rescheduled=rescheduled,
                )
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning("divide_api.watchdog_recovery.failed", error=str(exc))

    # Fix: Periodic PVE sync background task.
    # Syncs all RUNNING drills with actual PVE state every 30s.
    # Detects VM deletion and auto-transitions runs to FAILED.
    pve_sync_task = None
    pve_sync_interval_sec = getattr(settings, "pve_sync_interval_sec", 30) or 30

    if pve_sync_interval_sec > 0:
        import asyncio

        async def _pve_sync_loop() -> None:
            from app.db.session import get_sessionmaker
            from app.runners.runner import build_runner
            from app.db.models import RunStatus, AssetStatus, AuditAction, Run

            sm = get_sessionmaker()
            log.info(
                "divide_api.pve_sync.started",
                interval_sec=pve_sync_interval_sec,
            )

            while True:
                try:
                    async with sm() as session:
                        runs = (
                            await session.execute(
                                select(Run)
                                .where(Run.status == RunStatus.RUNNING)
                                .options(selectinload(Run.assets))
                            )
                        ).scalars().all()

                        for run in runs:
                            if not run.assets:
                                continue

                            runner = build_runner()
                            adapter = runner._adapter

                            for asset in run.assets:
                                if not asset.pve_vmid or not asset.pve_node:
                                    continue

                                try:
                                    state = await adapter.get_vm_state(
                                        asset.pve_vmid, asset.pve_node
                                    )

                                    # Update IP if discovered
                                    if state.ip and asset.pve_ip != state.ip:
                                        asset.pve_ip = state.ip
                                        await session.flush()

                                    # Detect VM deletion
                                    if state.status == "missing" or state.status == "stopped":
                                        if asset.status != AssetStatus.STOPPED:
                                            old_status = asset.status
                                            asset.status = AssetStatus.STOPPED
                                            asset.cleaned_at = datetime.now(timezone.utc)
                                            await session.flush()

                                            # Write audit log
                                            audit = models.AuditLog(
                                                run_id=run.id,
                                                asset_id=asset.id,
                                                action=AuditAction.ASSET_STATUS_SYNCED,
                                                actor="system:pve_sync",
                                                detail={
                                                    "old_status": old_status.value,
                                                    "new_status": "stopped",
                                                    "pve_status": state.status,
                                                    "auto_detected": True,
                                                },
                                            )
                                            session.add(audit)
                                            await session.flush()

                                            # If all assets are stopped, fail the run
                                            all_stopped = all(
                                                a.status == AssetStatus.STOPPED
                                                for a in run.assets
                                            )
                                            if all_stopped:
                                                run.status = RunStatus.FAILED
                                                run.ended_at = datetime.now(timezone.utc)
                                                run.error = "VM deleted or stopped outside of div:ide control"
                                                await session.flush()

                                                fail_audit = models.AuditLog(
                                                    run_id=run.id,
                                                    action=AuditAction.RUN_FAILED,
                                                    actor="system:pve_sync",
                                                    detail={
                                                        "reason": "vm_deleted_outside_control",
                                                        "asset_id": asset.id,
                                                    },
                                                )
                                                session.add(fail_audit)
                                                await session.flush()

                                                log.warning(
                                                    "divide_api.pve_sync.run_failed run_id=%s reason=vm_deleted",
                                                    run.id,
                                                )

                                except Exception as exc:  # noqa: BLE001
                                    log.debug(
                                        "divide_api.pve_sync.asset_sync_failed run_id=%s asset_id=%s error=%s",
                                        run.id,
                                        asset.id,
                                        str(exc),
                                    )

                        await session.commit()

                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "divide_api.pve_sync.error", error=str(exc)
                    )

                await asyncio.sleep(pve_sync_interval_sec)

        pve_sync_task = asyncio.create_task(_pve_sync_loop())

    yield

    # Cancel the janitor (if running) before tearing down other
    # resources so the cleanup loop doesn't fire after the bus is
    # closed.
    if janitor_task is not None:
        janitor_task.cancel()
        try:
            await janitor_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        log.info("divide_api.orphan_janitor.stopped")

    # Cancel the PVE sync task (if running) on shutdown.
    if pve_sync_task is not None:
        pve_sync_task.cancel()
        try:
            await pve_sync_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        log.info("divide_api.pve_sync.stopped")

    # R1: tear down the RedisEventBus bridge thread + redis pool.
    # InProcessEventBus has nothing to close. The factory caches
    # the bus at module load; we close the cached instance.
    try:
        from app.services.event_bus import build_event_bus

        bus = build_event_bus()
        if hasattr(bus, "close"):
            bus.close()
    except Exception as exc:  # pragma: no cover - best-effort
        log.warning("divide_api.event_bus.close_failed", error=str(exc))

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

    # Q14: install global exception handlers so any unhandled
    # exception (e.g. sql IntegrityError that slipped past a
    # router's ``except`` chain) returns structured JSON instead
    # of Uvicorn's default text/plain "Internal Server Error".
    # The portal's Q8 ``detailFromError`` helper expects
    # ``{"detail": "..."}`` to surface the message in the toast.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(  # noqa: ARG001
        request: Request, exc: Exception
    ) -> JSONResponse:
        # HTTPException + RequestValidationError + everything
        # FastAPI handles natively is caught by their respective
        # built-in handlers before this one runs. So this is only
        # the catch-all for things like SQLAlchemyError, asyncio
        # errors, or unanticipated runtime exceptions.
        log.exception(
            "divide_api.unhandled_exception",
            path=str(request.url.path),
            method=request.method,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "internal server error; the request was not "
                    "completed. Check /api/v1/admin/service-status "
                    "for cluster health and report this URL+method "
                    "to the operator."
                ),
                "path": str(request.url.path),
                "method": request.method,
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error_handler(  # noqa: ARG001
        request: Request, exc: IntegrityError
    ) -> JSONResponse:
        # Top-level safety net for any router that forgets to
        # catch IntegrityError locally (we added router-level
        # catches in Q14 too, but defence in depth).
        msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        log.warning(
            "divide_api.integrity_error",
            path=str(request.url.path),
            detail=msg[:300],
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": (
                    f"transaction integrity error: {msg}. "
                    "Retry the request; if it persists, capture "
                    "/api/v1/admin/service-status and report."
                ),
                "path": str(request.url.path),
                "method": request.method,
            },
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
    # F11: drill debrief artifact (markdown play-by-play for
    # leadership hand-off). Same prefix as /report so the URL
    # shape is consistent: /api/v1/drills/{id}/debrief.md.
    app.include_router(debrief.router, prefix="/api/v1/drills", tags=["debrief"])
    app.include_router(proxmox.router, prefix="/api/v1/proxmox", tags=["proxmox"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(exercises.router, prefix="/api/v1/exercises", tags=["exercises"])
    app.include_router(templates.router, prefix="/api/v1/templates", tags=["templates"])
    app.include_router(events.router, prefix="/api/v1", tags=["events"])
    # Q21: global audit search across all runs.
    app.include_router(audit.router, prefix="/api/v1/audit", tags=["audit"])

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
