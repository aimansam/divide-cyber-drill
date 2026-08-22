#!/usr/bin/env python3
"""End-to-end smoke for the runner.

Loads a Scenario YAML, validates it against the schema, inserts a
Scenario row + Run + Asset rows into the DB, runs the runner against a
mock Proxmox adapter, and verifies the DB end state.

This proves the happy path works without any PVE connectivity.

Usage:
    python tools/run_smoke.py [scenario-file]

Defaults to examples/scenarios/lateral-movement-baseline.scenario.yaml
(smaller, faster).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.db.session import get_sessionmaker
from app.runners.adapter import ProxmoxAdapter
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunRequest

ROOT = Path(__file__).resolve().parent.parent


async def _smoke(scenario_path: Path) -> int:
    # 1. Load + validate YAML
    spec = yaml.safe_load(scenario_path.read_text())
    print(f"[1/5] loaded {scenario_path.name} (kind={spec['kind']})")

    # 2. Set up in-memory DB
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine=engine)
    print("[2/5] in-memory DB created with 4 tables")

    # 3. Insert Scenario row
    async with sm() as session:
        m = spec["metadata"]
        scenario = models.Scenario(
            name=m["name"],
            title=m["title"],
            version=m["version"],
            difficulty=m["difficulty"],
            duration_min=m["duration_min"],
            tags=m.get("tags", []),
            spec=spec,
            authors=m.get("authors", []),
            source_path=(
            str(scenario_path.relative_to(ROOT))
            if scenario_path.is_absolute()
            else str(scenario_path)
        ),
        )
        session.add(scenario)
        await session.commit()
        await session.refresh(scenario)
        print(f"[3/5] inserted Scenario id={scenario.id} name={scenario.name!r}")

    # 4. Run the runner with a MockProxmoxAdapter
    #    Seed a VMID for every template the scenario references, so the
    #    runner can find them.
    adapter = MockProxmoxAdapter()
    spec_assets = spec["spec"]["assets"]
    for asset_spec in spec_assets:
        template_name = asset_spec["template"]
        vmid = await adapter.allocate_vmid()
        adapter.seed_template(template_name, vmid)
    runner = Runner(adapter=adapter)

    async with sm() as session:
        req = RunRequest(
            scenario_id=scenario.id,
            started_by="smoke-script",
        )
        result = await runner.start_run(req, session)
        # Verify the Run and its Assets got created.
        run = (
            await session.execute(select(models.Run).where(models.Run.id == result.run_id))
        ).scalar_one()
        assets = (
            await session.execute(
                select(models.Asset).where(models.Asset.run_id == result.run_id)
            )
        ).scalars().all()

    print(
        f"[4/5] runner produced Run id={run.id} status={run.status.value!r} "
        f"with {len(assets)} Asset(s): "
        f"{[(a.role, a.pve_vmid, a.pve_ip) for a in assets]}"
    )

    # 5. Stop the run and verify teardown
    async with sm() as session:
        stopped = await runner.stop_run(run.id, reason="smoke-test done", session=session)

    print(
        f"[5/5] runner stopped Run id={stopped.id} status={stopped.status.value!r}; "
        f"assets stopped: {[(a.role, a.status.value) for a in stopped.assets]}"
    )

    # Final assertions
    assert run.status == models.RunStatus.SUCCEEDED, f"expected SUCCEEDED, got {run.status}"
    assert stopped.status == models.RunStatus.SUCCEEDED, "stop should leave status SUCCEEDED"
    assert all(a.status == models.AssetStatus.STOPPED for a in stopped.assets), (
        "not all assets stopped"
    )
    assert len(adapter.cloned) == len(assets), "MockProxmox didn't clone each asset"
    assert len(adapter.stopped) == len(assets), "MockProxmox didn't stop each asset"

    print("\nSMOKE OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "scenario",
        nargs="?",
        type=Path,
        default=ROOT / "examples" / "scenarios" / "lateral-movement-baseline.scenario.yaml",
        help="Scenario YAML (default: lateral-movement-baseline).",
    )
    args = parser.parse_args(argv)

    if not args.scenario.is_file():
        print(f"error: {args.scenario} does not exist", file=sys.stderr)
        return 2
    return asyncio.run(_smoke(args.scenario))


if __name__ == "__main__":
    raise SystemExit(main())
