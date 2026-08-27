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

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from app.db import models
from app.db.models import AssetStatus, AuditAction, RunStatus
from app.observability import (
    inc_run_started,
    inc_run_terminal,
    record_adapter_call,
    record_cancel,
)
from app.runners.adapter import CloneSpec, NetworkSpec, ProxmoxAdapter
from app.services import telemetry as _telemetry
from app.services.event_recorder import record_event as _record_event
from app.db.models import TelemetrySeverity as _TS


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
    # F6: optional exercise + team binding.
    exercise_id: int | None = None
    team: str | None = None
    # F7: optional template this run is spawned from. The runner
    # uses the template's ``snapshot`` to pre-stage assets / flags
    # rather than re-deriving them from the live scenario row
    # (handy for replaying a frozen state).
    template_id: int | None = None


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

        # F3 multi-VM scenarios: build the bridge plan from spec.networks[].
        # We create one Linux bridge per network declaration, then attach
        # each asset to the bridges its ``spec.networks[]`` array names.
        # Bridges are sequential (vmbr100, vmbr101, …) so they don't
        # collide with operator-managed vmbr0 / vmbr1.
        networks_spec = spec.get("networks") or []
        bridges_by_name: dict[str, str] = {}
        for idx, net_spec in enumerate(networks_spec):
            # 100+offset keeps us out of PVE's well-known vmbr0..vmbr99.
            bridge = f"vmbr{100 + idx}"
            bridges_by_name[net_spec["name"]] = bridge
            await self._adapter.create_bridge(
                NetworkSpec(
                    bridge=bridge,
                    cidr=net_spec.get("cidr", ""),
                    isolation=net_spec.get("isolation", "tight"),
                    egress=net_spec.get("egress", "blocked"),
                    dhcp=net_spec.get("dhcp", True),
                )
            )
            log.info(
                "runner.networks.bridge_created name=%s bridge=%s cidr=%s",
                net_spec["name"], bridge, net_spec.get("cidr"),
            )

        # Pick node.
        nodes = await self._adapter.list_nodes()
        if not nodes:
            raise RunnerError("adapter reports zero PVE nodes")
        node = req.node or nodes[0]

        # 1. Create Run (pending) + Asset (planned) rows.
        # F6 + F7: propagate exercise_id + team + template_id.
        run = models.Run(
            scenario_id=scenario.id,
            status=RunStatus.PENDING,
            started_by=req.started_by,
            exercise_id=req.exercise_id,
            team=req.team,
            template_id=req.template_id,
        )
        session.add(run)
        await session.flush()
        # F8: emit run.started event.
        await _record_event(
            session,
            run_id=run.id,
            kind="run.started",
            source="runner",
            severity=_TS.INFO,
            payload={
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "started_by": req.started_by,
                "exercise_id": req.exercise_id,
                "team": req.team,
                "template_id": req.template_id,
            },
        )

        # F3 follow-up: honor ``spec.assets[].count`` so a single
        # declared asset can spawn multiple clones (e.g.
        # ``victim_workstation count: 2`` -> two VM rows). The
        # generated ``role`` for instance N is
        # ``<declared_role>_<N>`` (1-indexed); single-count assets
        # keep the declared role verbatim (no suffix).
        asset_count_total = 0
        for asset_spec in assets_spec:
            count = int(asset_spec.get("count") or 1)
            count = max(1, min(count, 64))  # schema already enforces; clamp defensively
            base_role = asset_spec["role"]
            for instance in (range(count) if count > 1 else [0]):
                # Use _N suffix only when count > 1; instance 0 means
                # "single, use declared role verbatim".
                role = (
                    f"{base_role}_{instance + 1}"
                    if count > 1
                    else base_role
                )
                session.add(
                    models.Asset(
                        run_id=run.id,
                        role=role,
                        kind=asset_spec.get("kind", "vm"),
                        template=asset_spec["template"],
                        status=AssetStatus.PLANNED,
                    )
                )
                asset_count_total += 1
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

        # 2b. Schedule the watchdog (L2 2.8). The watchdog checks after
        #     ``drill_timeout_min`` if the run is still RUNNING and, if
        #     so, transitions it to TIMEOUT. The task is fire-and-forget;
        #     it owns its own session lifecycle.
        self._schedule_watchdog(run.id, node, len(assets_spec))

        # 3. Clone + start each asset. On error, mark run FAILED and tear
        #    down whatever was already created.
        cloned_so_far: list[models.Asset] = []
        # Bridges we created during this run; tracked so teardown
        # (best-effort) can ask the adapter to remove them.
        bridges_created: list[str] = list(bridges_by_name.values())
        # Spawn one clone per generated row. The role of each row
        # is either the declared role (count == 1) or
        # ``<declared>_<N>`` (count > 1, N is 1-indexed). The
        # _spawn_asset method receives both the asset row and the
        # original asset_spec so it knows the declaring YAML.
        for asset_spec in assets_spec:
            count = int(asset_spec.get("count") or 1)
            base_role = asset_spec["role"]
            for instance_idx in (range(count) if count > 1 else [0]):
                instance_role = (
                    f"{base_role}_{instance_idx + 1}"
                    if count > 1
                    else base_role
                )
                asset = (
                    await session.execute(
                        select(models.Asset)
                        .where(models.Asset.run_id == run.id)
                        .where(models.Asset.role == instance_role)
                    )
                ).scalar_one()
                try:
                    # F3: stash bridges_by_name on the asset so _spawn_asset
                    # can read it (no method-signature change). The asset is
                    # a SQLAlchemy instance; attaching ad-hoc attributes is
                    # safe because we drop it on session.flush boundaries.
                    asset._f3_bridges_by_name = bridges_by_name  # type: ignore[attr-defined]
                    # F6: stash exercise + team attrs for the spawner log.
                    asset._f6_exercise_id = req.exercise_id  # type: ignore[attr-defined]
                    asset._f6_team = req.team  # type: ignore[attr-defined]
                    await self._spawn_asset(
                        session=session,
                        asset=asset,
                        asset_spec=asset_spec,
                        node=node,
                        actor=req.started_by,
                    )
                    # F8: emit asset.running (after spawn + boot).
                    await _record_event(
                        session,
                        run_id=run.id,
                        asset_id=asset.id,
                        kind="asset.running",
                        source="runner",
                        severity=_TS.INFO,
                        payload={
                            "role": asset.role,
                            "kind": asset.kind,
                            "template": asset.template,
                            "pve_vmid": asset.pve_vmid,
                        },
                    )
                    cloned_so_far.append(asset)
                except Exception as spawn_exc:
                    run.status = RunStatus.FAILED
                    run.ended_at = datetime.now(timezone.utc)
                    run.error = f"{type(spawn_exc).__name__}: {spawn_exc}"
                    asset.status = AssetStatus.FAILED
                    asset.error = str(spawn_exc)
                    await self._best_effort_teardown(cloned_so_far)
                    # Tear down bridges we created so a retry starts
                    # clean. Best-effort: a real-PVE bridge is
                    # operator-owned and remove_bridge is a no-op;
                    # the mock removes them.
                    for br in bridges_created:
                        try:
                            await self._adapter.remove_bridge(br)
                        except Exception as bridge_exc:  # noqa: BLE001
                            log.warning(
                                "runner.networks.remove_bridge_failed "
                                "bridge=%s err=%s",
                                br, bridge_exc,
                            )
                    inc_run_terminal(
                        outcome="failed", adapter=_adapter_label(self._adapter)
                    )
                    await self._audit(
                        session,
                        action=AuditAction.RUN_FAILED,
                        actor=req.started_by,
                        run_id=run.id,
                        scenario_id=scenario.id,
                        details={
                            "error": str(spawn_exc),
                            "role": asset.role,
                        },
                    )
                    await session.commit()
                    raise

        # 4. F5: plant flags declared in spec.flags[]. Each flag
        # has a planted_on_role; for F5.2 we record the planting
        # intent (audit row + run-level metadata) so the operator
        # sees the chain. The actual filesystem write is done via
        # cloud-init user_data on the target asset; that comes
        # for free when scenarios author a user_data snippet
        # referencing spec.flags[].id. See docs/F5-SCORING.md §3
        # for the user_data recipe.
        flags_spec = spec.get("flags") or []
        planted_count = 0
        for flag_spec in flags_spec:
            planted_role = flag_spec.get("planted_on_role")
            if not planted_role:
                continue
            # Find the matching asset(s) so the audit row can
            # link to the asset_id when the planting intent is
            # associated with a specific cloned VM.
            asset_link = None
            for asset in cloned_so_far:
                if asset.role == planted_role and asset.pve_vmid:
                    asset_link = asset.id
                    break
            await self._audit(
                session,
                action=AuditAction.FLAG_PLANTED,
                actor=req.started_by,
                run_id=run.id,
                asset_id=asset_link,
                details={
                    "flag_id": flag_spec.get("id"),
                    "side": flag_spec.get("side"),
                    "planted_on_role": planted_role,
                    "base_points": flag_spec.get("base_points"),
                    "decay_window_seconds": flag_spec.get(
                        "decay_window_seconds"
                    ),
                    # Do NOT log the value; the API surfaces the
                    # value to authenticated clients only.
                    "value_present": bool(flag_spec.get("value")),
                },
            )
            planted_count += 1
        if flags_spec:
            log.info(
                "runner.flags.planted run_id=%s planted=%s declared=%s",
                run.id, planted_count, len(flags_spec),
            )

        # 5. All assets up — flip run to SUCCEEDED.
        run.status = RunStatus.SUCCEEDED
        run.ended_at = datetime.now(timezone.utc)
        # F3: tear down bridges we created. The drill is over; the
        # topology it was building is gone. Best-effort, matching
        # the failure path above. Real-PVE remove_bridge is no-op;
        # mock removes them.
        for br in bridges_created:
            try:
                await self._adapter.remove_bridge(br)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "runner.networks.remove_bridge_failed bridge=%s err=%s",
                    br, exc,
                )
        # Q17: tear down the spawned VMs too. The drill is over;
        # without this loop every successful drill leaves a clone
        # running on PVE forever (Q14 left 8 such orphans behind).
        # Best-effort via the same helper the failure path uses:
        # a flaky destroy here cannot roll back a successful run,
        # and the per-asset ``status`` flips to ``ORPHANED`` so an
        # operator + future janitor can clean up.
        await self._best_effort_teardown(cloned_so_far)
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
        # F8: emit run.completed event (BEFORE the final commit so
        # the row is part of the same transaction).
        await _record_event(
            session,
            run_id=run.id,
            kind="run.completed",
            source="runner",
            severity=_TS.INFO,
            payload={
                "scenario_id": scenario.id,
                "asset_count": len(assets_spec),
                "duration_sec": run.duration_sec,
            },
        )

        await session.commit()

        # Telemetry (L2 2.11). Build sinks from the scenario spec and
        # fire-and-forget dispatch. Telemetry is best-effort — failures
        # never propagate; ``dispatch`` swallows them.
        sinks = _telemetry.build_sinks_from_spec(scenario.spec)
        await _telemetry.dispatch(
            sinks,
            {
                "type": "run.completed",
                "run_id": run.id,
                "scenario_id": scenario.id,
                "started_by": run.started_by,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "duration_sec": run.duration_sec,
                "asset_count": len(assets_spec),
            },
        )

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
                    # Q17: explicit success marker. Previously the
                    # code only set ORPHANED on failure; if the
                    # destroy succeeded but stop failed earlier,
                    # the asset could end up FAILED. Be explicit.
                    if asset.status != AssetStatus.FAILED:
                        asset.status = AssetStatus.STOPPED
                except Exception:
                    asset.status = AssetStatus.ORPHANED
            else:
                asset.status = AssetStatus.STOPPED

        run.status = RunStatus.SUCCEEDED
        run.ended_at = datetime.now(timezone.utc)
        inc_run_terminal(outcome="succeeded", adapter=_adapter_label(self._adapter))
        # Q17: distinguish operator-initiated stop from trainee
        # cancel. ``/stop`` writes RUN_STOPPED; ``/cancel`` still
        # writes RUN_CANCELLED. Audit log readers can now answer
        # "did the operator stop this, or did the trainee cancel?"
        # without diffing the reason text.
        await self._audit(
            session,
            action=AuditAction.RUN_STOPPED,
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
        # F3 multi-VM scenarios: attach NICs to each bridge the asset
        # declares in ``asset_spec.networks[]``. NIC IDs are sequential
        # starting from 0 (net0, net1, …); we use ``enumerate`` so the
        # first declared network becomes net0 — which matters for
        # PVE ``qm config`` output and for scenarios that key off the
        # primary NIC. ``bridges_by_name`` is computed once at the
        # start of start_run and passed in via the call site.
        await session.flush()
        await self._attach_asset_networks(
            asset=asset,
            asset_spec=asset_spec,
            bridges_by_name=asset._f3_bridges_by_name,  # type: ignore[attr-defined]
            node=node,
        )

        await self._audit(
            session,
            action=AuditAction.ASSET_SPAWNED,
            actor=actor,
            run_id=asset.run_id,
            asset_id=asset.id,
            details={"role": asset.role, "vmid": result.vmid, "ip": state.ip},
        )

    async def _attach_asset_networks(
        self,
        *,
        asset: models.Asset,
        asset_spec: dict,
        bridges_by_name: dict[str, str],
        node: str,
    ) -> None:
        """F3: attach NICs to the bridges this asset declares.

        Iterates ``asset_spec.networks[]`` in declaration order,
        records each as an additional NIC on the freshly cloned VM.
        Silently skips networks whose name is not in
        ``bridges_by_name`` (the runner validates the network
        declarations exist before this is called, so this should be
        unreachable in practice — but we don't want a typo to
        brick the runner with a KeyError here).
        """
        asset_networks = asset_spec.get("networks") or []
        for nic_id, net_name in enumerate(asset_networks):
            bridge = bridges_by_name.get(net_name)
            if bridge is None:
                log.warning(
                    "runner.networks.unknown_network role=%s network=%s "
                    "(bridge not found)",
                    asset.role, net_name,
                )
                continue
            await self._adapter.attach_network(
                asset.pve_vmid, node, bridge, nic_id
            )
            log.info(
                "runner.networks.attached role=%s vmid=%s bridge=%s nic_id=%s",
                asset.role, asset.pve_vmid, bridge, nic_id,
            )

    async def _best_effort_teardown(self, assets: list[models.Asset]) -> None:
        for a in assets:
            if a.pve_vmid is None or not a.pve_node:
                continue
            try:
                await self._adapter.stop_vm(a.pve_vmid, a.pve_node, force=True)
                await self._adapter.destroy_vm(a.pve_vmid, a.pve_node)
                a.status = AssetStatus.STOPPED
            except Exception as exc:  # noqa: BLE001
                # Q17: surface the failure so the operator can
                # see why the VM is orphaned (previously the
                # error was swallowed with no log + no asset.error).
                log.warning(
                    "runner.assets.teardown_failed asset_id=%s vmid=%s err=%s",
                    a.id, a.pve_vmid, exc,
                )
                a.status = AssetStatus.ORPHANED
                a.error = f"teardown failed: {exc}"

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

    # --- watchdog (L2 2.8) --------------------------------------------

    def _schedule_watchdog(
        self, run_id: int, node: str, asset_count: int
    ) -> None:
        """Spawn the timeout watchdog as a background asyncio task.

        Idempotent: if the timeout is disabled (env override) or
        non-positive, no task is scheduled. Otherwise the task sleeps
        for ``drill_timeout_min * 60`` seconds and then invokes
        :meth:`_watchdog_timeout_fire`. The task owns its own session,
        so it survives the request-response cycle that started the run.
        """
        enabled = getattr(settings, "drill_timeout_enabled", True)
        timeout_min = getattr(settings, "drill_timeout_min", 0) or 0
        if not enabled or timeout_min <= 0:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (e.g. synchronous test). Watchdog is a safety net;
            # skip and rely on manual cancel.
            logging.getLogger(__name__).info(
                "runner.watchdog.no_loop run_id=%s (skipping)", run_id
            )
            return

        loop.create_task(
            self._watchdog_timeout_fire(
                run_id=run_id,
                node=node,
                timeout_min=timeout_min,
                asset_count=asset_count,
            )
        )

    async def _watchdog_timeout_fire(
        self, *, run_id: int, node: str, timeout_min: int, asset_count: int
    ) -> None:
        """Sleep then flip the run to TIMEOUT if still RUNNING.

        Best-effort: if anything fails (DB down, adapter crash), log
        and move on. The audit + metric paths are fire-and-forget;
        we never raise out of the watchdog.
        """
        try:
            await asyncio.sleep(timeout_min * 60)
        except asyncio.CancelledError:
            return  # Run terminated on its own; no-op.

        sm = _sessionmaker()
        try:
            async with sm() as session:
                run = (
                    await session.execute(
                        select(models.Run).where(models.Run.id == run_id)
                    )
                ).scalar_one_or_none()
                if run is None:
                    log.info("runner.watchdog.run_gone run_id=%s", run_id)
                    return
                if run.status != RunStatus.RUNNING:
                    log.info(
                        "runner.watchdog.run_already_terminal run_id=%s status=%s",
                        run_id,
                        run.status.value,
                    )
                    return

                # Best-effort adapter teardown.
                assets = (
                    await session.execute(
                        select(models.Asset).where(models.Asset.run_id == run_id)
                    )
                ).scalars().all()
                for asset in assets:
                    if asset.pve_vmid is None or not asset.pve_node:
                        continue
                    try:
                        await self._adapter.stop_vm(
                            asset.pve_vmid, asset.pve_node, force=True
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "runner.watchdog.stop_failed vmid=%s err=%s",
                            asset.pve_vmid,
                            exc,
                        )
                    try:
                        await self._adapter.destroy_vm(
                            asset.pve_vmid, asset.pve_node
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "runner.watchdog.destroy_failed vmid=%s err=%s",
                            asset.pve_vmid,
                            exc,
                        )
                    asset.status = AssetStatus.STOPPED

                run.status = RunStatus.TIMEOUT
                run.ended_at = datetime.now(timezone.utc)
                run.error = f"auto-timeout after {timeout_min} min"
                inc_run_terminal(
                    outcome="timeout", adapter=_adapter_label(self._adapter)
                )
                await self._audit(
                    session,
                    action=AuditAction.RUN_TIMEOUT,
                    actor="watchdog",
                    run_id=run.id,
                    details={
                        "timeout_min": timeout_min,
                        "asset_count": asset_count,
                    },
                )
                await session.commit()
                log.info(
                    "runner.watchdog.timeout_fired run_id=%s timeout_min=%s",
                    run_id,
                    timeout_min,
                )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "runner.watchdog.failed run_id=%s err=%s",
                run_id,
                exc,
                exc_info=True,
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
