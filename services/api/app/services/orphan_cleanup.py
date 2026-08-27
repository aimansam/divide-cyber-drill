"""Q22: orphan-asset janitor.

Background
----------

Q17 wired the ``Asset.status`` flip to ``AssetStatus.ORPHANED``
when the teardown loop fails to ``destroy_vm``. The comment at
runner.py:736-744 explicitly says "an operator + future janitor
can clean up". The janitor didn't ship with Q17.

What this module does:

  * ``cleanup_orphans()`` -- iterate every asset where
    ``status == ORPHANED``, retry ``stop_vm(force=True) +
    destroy_vm``, flip to ``STOPPED`` on success and stamp
    ``cleaned_at``. Writes one ``asset.cleaned`` audit row per
    success.
  * ``list_orphans()`` -- dry-run variant used by the UI's
    preview pane and the janitor's own guard rails.

Policy:

  * ``asset.pve_vmid`` must be set -- an orphan that never got a
    VMID (e.g. clone failed at allocation) can't be cleaned via
    PVE; we leave those rows alone and skip with a note.
  * The owning run must be in a terminal status -- if a drill is
    still RUNNING/PENDING, the operator meant something else, so
    409 + skip.
  * ``grace_minutes`` (default 5) -- refuse to clean orphans
    younger than that. Avoids racing with in-progress teardown.
  * Idempotent -- destroy_vm on a missing VM is a no-op per
    ``adapter.py:118``; calling it twice is safe.

Audit:

  * One ``asset.cleaned`` row per asset successfully released.
  * Failed assets get ``asset.error`` updated with the new error
    text (overwriting the previous); they stay ``ORPHANED``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Asset,
    AssetStatus,
    AuditAction,
    AuditLog,
    Run,
    RunStatus,
)
from app.runners.adapter import ProxmoxAdapter


log = structlog.get_logger(__name__)


# Default grace period before an orphan is eligible for cleanup.
# Tunable via the endpoint query param.
DEFAULT_GRACE_MINUTES = 5


@dataclass
class OrphanCandidate:
    """One asset row that's eligible for cleanup."""

    asset_id: int
    run_id: int
    run_status: str
    role: str
    pve_vmid: int | None
    pve_node: str | None
    error: str | None
    orphaned_at: datetime | None  # best-known "when did it become an orphan"
    age_seconds: int


@dataclass
class CleanupFailure:
    asset_id: int
    run_id: int
    pve_vmid: int | None
    error: str


@dataclass
class CleanupResult:
    scanned: int
    destroyed: int
    failed: list[CleanupFailure]
    skipped_running: list[int]  # asset ids we refused to touch

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "destroyed": self.destroyed,
            "failed": [
                {
                    "asset_id": f.asset_id,
                    "run_id": f.run_id,
                    "pve_vmid": f.pve_vmid,
                    "error": f.error,
                }
                for f in self.failed
            ],
            "skipped_running": list(self.skipped_running),
        }


async def list_orphans(
    session: AsyncSession,
    *,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    asset_ids: Iterable[int] | None = None,
) -> list[OrphanCandidate]:
    """Return the orphans that ``cleanup_orphans`` would act on.

    Honours the same skip rules as cleanup itself:

      * ``run.status in (RUNNING, PENDING)``  -- don't touch
      * ``asset.pve_vmid IS NULL``           -- nothing to destroy on PVE
      * ``asset.created_at`` newer than grace -- too fresh; teardown
                                              might still be in flight
    """
    now = datetime.now(timezone.utc)
    grace_cutoff = now.timestamp() - grace_minutes * 60
    stmt = select(Asset, Run).join(Run, Asset.run_id == Run.id).where(
        Asset.status == AssetStatus.ORPHANED
    )
    if asset_ids is not None:
        ids = list(asset_ids)
        if not ids:
            return []
        stmt = stmt.where(Asset.id.in_(ids))
    rows = (await session.execute(stmt)).all()
    out: list[OrphanCandidate] = []
    for asset, run in rows:
        # Orphaned-when is best-approximated by updated_at, falling
        # back to created_at when updated_at isn't set (older rows).
        stamp = asset.updated_at or asset.created_at
        if stamp is not None and stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (
            int(now.timestamp() - stamp.timestamp())
            if stamp is not None
            else 0
        )
        if run.status in (RunStatus.RUNNING, RunStatus.PENDING):
            continue
        if asset.pve_vmid is None:
            continue
        # Only skip when younger than grace. Older orphans are fair game.
        if stamp is not None and stamp.timestamp() > grace_cutoff:
            continue
        out.append(
            OrphanCandidate(
                asset_id=asset.id,
                run_id=asset.run_id,
                run_status=run.status.value,
                role=asset.role,
                pve_vmid=asset.pve_vmid,
                pve_node=asset.pve_node,
                error=asset.error,
                orphaned_at=stamp,
                age_seconds=age,
            )
        )
    out.sort(key=lambda c: c.orphaned_at or now, reverse=False)
    return out


async def cleanup_orphans(
    session: AsyncSession,
    adapter: ProxmoxAdapter,
    actor: str,
    *,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    asset_ids: Iterable[int] | None = None,
) -> CleanupResult:
    """Best-effort destroy every eligible orphan.

    Returns a CleanupResult summarising what was attempted. The
    endpoint translates this to JSON; the UI uses ``destroyed``
    and ``failed`` lengths for the toast.
    """
    candidates = await list_orphans(
        session,
        grace_minutes=grace_minutes,
        asset_ids=asset_ids,
    )
    failures: list[CleanupFailure] = []
    skipped: list[int] = []
    destroyed = 0

    # Re-query candidate asset rows so we have ORM-bound instances
    # to mutate + commit. ``list_orphans`` already validated the
    # shape; this is just the load-for-write step.
    if not candidates:
        return CleanupResult(scanned=0, destroyed=0, failed=[], skipped_running=[])
    cand_ids = [c.asset_id for c in candidates]
    rows = (
        await session.execute(select(Asset).where(Asset.id.in_(cand_ids)))
    ).scalars().all()

    for asset in rows:
        if asset.pve_vmid is None or not asset.pve_node:
            skipped.append(asset.id)
            continue
        # Re-check the run-status gate at write time so we don't
        # race a drill that became RUNNING between list and act.
        run = await session.get(Run, asset.run_id)
        if run is not None and run.status in (
            RunStatus.RUNNING,
            RunStatus.PENDING,
        ):
            skipped.append(asset.id)
            continue
        try:
            try:
                await adapter.stop_vm(asset.pve_vmid, asset.pve_node, force=True)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "orphan_cleanup.stop_failed asset_id=%s vmid=%s err=%s",
                    asset.id,
                    asset.pve_vmid,
                    exc,
                )
                # Don't bail: destroy may still succeed on a stopped VM.
            await adapter.destroy_vm(asset.pve_vmid, asset.pve_node)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "orphan_cleanup.destroy_failed asset_id=%s vmid=%s err=%s",
                asset.id,
                asset.pve_vmid,
                exc,
            )
            asset.status = AssetStatus.ORPHANED
            asset.error = f"cleanup retry failed: {exc}"
            failures.append(
                CleanupFailure(
                    asset_id=asset.id,
                    run_id=asset.run_id,
                    pve_vmid=asset.pve_vmid,
                    error=str(exc),
                )
            )
            continue
        # Success: flip status + stamp cleaned_at + audit row.
        now = datetime.now(timezone.utc)
        previous_error = asset.error
        asset.status = AssetStatus.STOPPED
        asset.error = None
        asset.cleaned_at = now
        session.add(
            AuditLog(
                action=AuditAction.ASSET_CLEANED,
                actor=actor,
                run_id=asset.run_id,
                asset_id=asset.id,
                details={
                    "vmid": asset.pve_vmid,
                    "node": asset.pve_node,
                    "previous_error": previous_error,
                },
            )
        )
        destroyed += 1

    if destroyed or failures:
        await session.commit()

    return CleanupResult(
        scanned=len(candidates),
        destroyed=destroyed,
        failed=failures,
        skipped_running=skipped,
    )
