"""Run a Scenario end-to-end against a ProxmoxAdapter.

This is the orchestrator. It owns the run lifecycle:

  pending -> running -> succeeded
                       \\-> failed
                       \\-> timeout (caller-imposed)
                       \\-> cancelled

The runner is **strict**: every asset is cloned, started, then on
teardown stopped and destroyed by this code path. There is no "attach
to existing VMID" mode yet (we can add it later without changing the
interface).

Concurrency model: assets are spawned sequentially for now. PVE clone
is fast but template-disk-bound; parallel clone is a future
optimisation.

Failure handling: any exception during clone or start transitions the
run to FAILED and best-effort tears down what was already created.
The error is recorded on `Run.error` and in the audit log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.db.models import AssetStatus, AuditAction, RunStatus
from app.observability import (
    inc_run_started,
    inc_run_terminal,
    record_adapter_call,
    record_cancel,
)
from app.runners.adapter import CloneSpec, ProxmoxAdapter


def _adapter_label(adapter: ProxmoxAdapter) -> str:
    """``real`` or ``mock`` — used as a Prometheus label so we can graph
    live vs test traffic without distinguishing class names."""
    cls = type(adapter).__name__
    if cls == "RealProxmoxAdapter":
        return "real"
    return "mock"


@dataclass(frozen=True)
class RunRequest:
    """Inputs to start a new Run."""

    scenario_id: int
    started_by: str | None = None
    # Optional override; defaults to first node returned by the adapter.
    node: str | None = None


@dataclass(frozen=True)
class RunResult:
    """Return value of `start_run` for the API layer."""

    run_id: int
    status: RunStatus


class RunnerError(RuntimeError):
    """Raised when the runner cannot complete a phase. Always actionable."""


class Runner:
    """Orchestrates one run at a time."""

    def __init__(self, adapter: ProxmoxAdapter) -> None:
        self._adapter = adapter

    # --- public API ------------------------------------------------------

    async def start_run(self, req: RunRequest, session: AsyncSession) -> RunResult:
        """Create Run row, clone + start each asset, flip to SUCCEEDED.

        Returns the new run id. The returned Run is committed (i.e. you
        can read it from a fresh session).
        """
        scenario = (
            await session.execute(
                select(models.Scenario).where(models.Scenario.id == req.scenario_id)
            )
        ).scalar_one_or_none()
        if scenario is None:
            raise RunnerError(f"scenario id={req.scenario_id} not found")

        spec = scenario.spec.get("spec") or scenario.spec
        assets_spec = spec.get("assets") or []
        if not assets_spec:
            raise RunnerError("scenario has no assets")

        # Pick node.
        nodes = await self._adapter.list_nodes()
        if not nodes:
            raise RunnerError("adapter reports zero PVE nodes")
        node = req.node or nodes[0]

        # 1. Create Run (pending) + Asset (planned) rows.
        run = models.Run(
            scenario_id=scenario.id,
            status=RunStatus.PENDING,
            started_by=req.started_by,
        )
        session.add(run)
        await session.flush()

        for asset_spec in assets_spec:
            session.add(
                models.Asset(
                    run_id=run.id,
                    role=asset_spec["role"],
                    kind=asset_spec.get("kind", "vm"),
                    template=asset_spec["template"],
                    status=AssetStatus.PLANNED,
                )
            )
        await session.flush()

        await self._audit(
            session,
            action=AuditAction.RUN_STARTED,
            actor=req.started_by,
            run_id=run.id,
            scenario_id=scenario.id,
            details={"node": node, "asset_count": len(assets_spec)},
        )

        # 2. Transition to RUNNING.
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        await session.flush()
        inc_run_started(adapter=_adapter_label(self._adapter))

        # 3. Clone + start each asset. On error, mark run FAILED and tear
        #    down whatever was already created.
        cloned_so_far: list[models.Asset] = []
        for asset_spec in assets_spec:
            asset = (
                await session.execute(
                    select(models.Asset)
                    .where(models.Asset.run_id == run.id)
                    .where(models.Asset.role == asset_spec["role"])
                )
            ).scalar_one()
            try:
                await self._spawn_asset(
                    session=session,
                    asset=asset,
                    asset_spec=asset_spec,
                    node=node,
                    actor=req.started_by,
                )
                cloned_so_far.append(asset)
            except Exception as exc:
                run.status = RunStatus.FAILED
                run.ended_at = datetime.now(timezone.utc)
                run.error = f"{type(exc).__name__}: {exc}"
                asset.status = AssetStatus.FAILED
                asset.error = str(exc)
                await self._best_effort_teardown(cloned_so_far)
                inc_run_terminal(outcome="failed", adapter=_adapter_label(self._adapter))
                await self._audit(
                    session,
                    action=AuditAction.RUN_FAILED,
                    actor=req.started_by,
                    run_id=run.id,
                    scenario_id=scenario.id,
                    details={"error": str(exc), "role": asset_spec["role"]},
                )
                await session.commit()
                raise

        # 4. All assets up — flip run to SUCCEEDED.
        run.status = RunStatus.SUCCEEDED
        run.ended_at = datetime.now(timezone.utc)
        await session.flush()
        inc_run_terminal(outcome="succeeded", adapter=_adapter_label(self._adapter))
        await self._audit(
            session,
            action=AuditAction.RUN_COMPLETED,
            actor=req.started_by,
            run_id=run.id,
            scenario_id=scenario.id,
            details={"asset_count": len(assets_spec)},
        )
        await session.commit()
        return RunResult(run_id=run.id, status=run.status)

    async def stop_run(
        self,
        run_id: int,
        reason: str = "user-requested",
        session: AsyncSession | None = None,
        actor: str | None = None,
    ) -> models.Run:
        """Stop every asset in a run and destroy them. Idempotent.

        Sets ``Run.status = SUCCEEDED`` (operator-initiated "the drill is
        done — clean up"). For trainee-initiated aborts use
        :meth:`cancel_run`, which sets ``CANCELLED`` instead.

        Pass `session` to participate in a caller's transaction; if None,
        the runner owns the session lifecycle via the global sessionmaker.
        """
        if session is not None:
            return await self._stop_run_impl(run_id, reason, actor, session)
        sm = _sessionmaker()
        async with sm() as session:
            return await self._stop_run_impl(run_id, reason, actor, session)

    async def cancel_run(
        self,
        run_id: int,
        reason: str = "user-requested",
        session: AsyncSession | None = None,
        actor: str | None = None,
    ) -> models.Run:
        """Abort a running drill. Symmetric with :meth:`stop_run`.

        Behaviour:
          * Validates the run exists and is in a non-terminal state
            (``PENDING`` or ``RUNNING``). If already terminal, raises
            :class:`RunnerError` (the router maps to 409 Conflict).
          * Stops and destroys every asset that was spawned (best-effort,
            matching the spawn failure path).
          * Sets ``Run.status = CANCELLED``, ``ended_at = now``,
            ``error = reason`` (so the audit + UI can show why).
          * Writes an audit ``RUN_CANCELLED`` entry with the reason +
            actor in details.

        Idempotent on the adapter side (destroy is 404-tolerant), but the
        DB transition is not — a second cancel on an already-cancelled
        run raises.
        """
        if session is not None:
            return await self._cancel_run_impl(run_id, reason, actor, session)
        sm = _sessionmaker()
        async with sm() as session:
            return await self._cancel_run_impl(run_id, reason, actor, session)

    async def _stop_run_impl(
        self,
        run_id: int,
        reason: str,
        actor: str | None,
        session: AsyncSession,
    ) -> models.Run:
        run = (
            await session.execute(select(models.Run).where(models.Run.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            raise RunnerError(f"run id={run_id} not found")
        assets = (
            await session.execute(
                select(models.Asset).where(models.Asset.run_id == run_id)
            )
        ).scalars().all()

        for asset in assets:
            if asset.pve_vmid is not None and asset.pve_node:
                try:
                    await self._adapter.stop_vm(asset.pve_vmid, asset.pve_node)
                    asset.status = AssetStatus.STOPPED
                except Exception as exc:
                    asset.status = AssetStatus.FAILED
                    asset.error = f"stop failed: {exc}"
                try:
                    await self._adapter.destroy_vm(asset.pve_vmid, asset.pve_node)
                except Exception:
                    asset.status = AssetStatus.ORPHANED
            else:
                asset.status = AssetStatus.STOPPED

        run.status = RunStatus.SUCCEEDED
        run.ended_at = datetime.now(timezone.utc)
        inc_run_terminal(outcome="succeeded", adapter=_adapter_label(self._adapter))
        await self._audit(
            session,
            action=AuditAction.RUN_CANCELLED,
            actor=actor,
            run_id=run.id,
            details={"reason": reason},
        )
        await session.commit()
        await session.refresh(run, attribute_names=["assets"])
        return run

    async def _cancel_run_impl(
        self,
        run_id: int,
        reason: str,
        actor: str | None,
        session: AsyncSession,
    ) -> models.Run:
        run = (
            await session.execute(select(models.Run).where(models.Run.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            raise RunnerError(f"run id={run_id} not found")
        if run.status not in (RunStatus.PENDING, RunStatus.RUNNING):
            raise RunnerError(
                f"run id={run_id} is in terminal state "
                f"{run.status.value!r}; cannot cancel"
            )

        assets = (
            await session.execute(
                select(models.Asset).where(models.Asset.run_id == run_id)
            )
        ).scalars().all()

        # Best-effort teardown — never raise from here; we want the run
        # row + audit entry to land even if the adapter is half-broken.
        for asset in assets:
            if asset.pve_vmid is not None and asset.pve_node:
                try:
                    await self._adapter.stop_vm(
                        asset.pve_vmid, asset.pve_node, force=True
                    )
                except Exception as exc:  # noqa: BLE001
                    asset.status = AssetStatus.ORPHANED
                    asset.error = f"stop failed during cancel: {exc}"
                    continue
                try:
                    await self._adapter.destroy_vm(asset.pve_vmid, asset.pve_node)
                except Exception as exc:  # noqa: BLE001
                    asset.status = AssetStatus.ORPHANED
                    asset.error = f"destroy failed during cancel: {exc}"
                    continue
                asset.status = AssetStatus.STOPPED
            else:
                # Asset never got as far as cloning — mark stopped so the
                # UI shows the row in a sensible state.
                asset.status = AssetStatus.STOPPED

        run.status = RunStatus.CANCELLED
        run.ended_at = datetime.now(timezone.utc)
        run.error = reason
        inc_run_terminal(outcome="cancelled", adapter=_adapter_label(self._adapter))
        record_cancel(result="ok")
        await self._audit(
            session,
            action=AuditAction.RUN_CANCELLED,
            actor=actor,
            run_id=run.id,
            details={"reason": reason, "actor": actor},
        )
        await session.commit()
        await session.refresh(run, attribute_names=["assets"])
        return run

    # --- internals -------------------------------------------------------

    async def _spawn_asset(
        self,
        session: AsyncSession,
        asset: models.Asset,
        asset_spec: dict,
        node: str,
        actor: str | None = None,
    ) -> None:
        template_vmid = await self._adapter.find_template(asset.template)
        if template_vmid is None:
            raise RunnerError(
                f"template {asset.template!r} not found on PVE "
                f"(role={asset.role!r})"
            )

        new_vmid = await self._adapter.allocate_vmid()
        resources = asset_spec.get("resources") or {}
        # PVE 9 enforces strict DNS-1123 names on the clone VMID; underscores
        # in the role (e.g. ``drill_vm``) violate that. We strip them from
        # both role and a sanitized copy for the VM name only; the asset's
        # ``role`` field on the DB row stays untouched.
        role = asset.role
        sanitized_role = role.replace("_", "")
        clone = CloneSpec(
            source_vmid=template_vmid,
            new_vmid=new_vmid,
            node=node,
            name=f"divide-{asset.run_id}-{sanitized_role}",
            cores=resources.get("cores"),
            sockets=resources.get("sockets"),
            ram_mb=resources.get("ram_mb"),
            disk_gb=resources.get("disk_gb"),
        )
        asset.status = AssetStatus.CLONING
        await session.flush()

        result = await self._adapter.clone_vm(clone)
        asset.pve_vmid = result.vmid
        asset.pve_node = result.node
        asset.status = AssetStatus.BOOTING
        await session.flush()

        await self._adapter.start_vm(result.vmid, result.node)
        state = await self._adapter.get_vm_state(result.vmid, result.node)
        asset.pve_ip = state.ip
        asset.status = (
            AssetStatus.RUNNING if state.status == "running" else AssetStatus.STOPPED
        )
        await session.flush()

        await self._audit(
            session,
            action=AuditAction.ASSET_SPAWNED,
            actor=actor,
            run_id=asset.run_id,
            asset_id=asset.id,
            details={"role": asset.role, "vmid": result.vmid, "ip": state.ip},
        )

    async def _best_effort_teardown(self, assets: list[models.Asset]) -> None:
        for a in assets:
            if a.pve_vmid is None or not a.pve_node:
                continue
            try:
                await self._adapter.stop_vm(a.pve_vmid, a.pve_node, force=True)
                await self._adapter.destroy_vm(a.pve_vmid, a.pve_node)
                a.status = AssetStatus.STOPPED
            except Exception:
                a.status = AssetStatus.ORPHANED

    async def _audit(
        self,
        session: AsyncSession,
        *,
        action: AuditAction,
        actor: str | None = None,
        scenario_id: int | None = None,
        run_id: int | None = None,
        asset_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        session.add(
            models.AuditLog(
                action=action,
                actor=actor,
                scenario_id=scenario_id,
                run_id=run_id,
                asset_id=asset_id,
                details=details or {},
            )
        )


def _sessionmaker():
    """Lazy import to avoid circular import at module load."""
    from app.db.session import get_sessionmaker

    return get_sessionmaker()


def _default_adapter() -> ProxmoxAdapter:
    """Pick the right adapter based on env.

    - If `PROXMOX_HOST` + `PROXMOX_TOKEN_ID` + `PROXMOX_TOKEN_SECRET` are
      all set, return a `RealProxmoxAdapter` against the live cluster.
    - Otherwise return `MockProxmoxAdapter` so dev/test/CLI keep working
      without a PVE token.

    This is the single decision point that swaps mock <-> real; the rest of
    the runner doesn't know which is in use.
    """
    from app.core.config import settings
    from app.runners.mock_adapter import MockProxmoxAdapter
    from app.runners.real_adapter import RealProxmoxAdapter

    p = settings.proxmox
    host = (p.host or "").strip()
    token_id = (p.token_id or "").strip()
    has_secret = p.token_secret is not None and bool(
        p.token_secret.get_secret_value()
    )
    if host and token_id and has_secret:
        try:
            return RealProxmoxAdapter.from_settings(p)
        except Exception:  # noqa: BLE001
            # Bad config: fall back to mock so the API still boots, but log.
            import logging

            logging.getLogger(__name__).warning(
                "PROXMOX_* env present but invalid; using MockProxmoxAdapter",
                exc_info=True,
            )
    return MockProxmoxAdapter()


def build_runner() -> Runner:
    """Build a `Runner` with the default adapter selection.

    Convenience factory used by FastAPI dependency injection and the CLI
    smoke tool. Pass `Runner(adapter=...)` explicitly in tests so the
    mock stays in your control.
    """
    return Runner(adapter=_default_adapter())
