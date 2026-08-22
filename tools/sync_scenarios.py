#!/usr/bin/env python3
"""Sync scenario YAML files into the DB.

Usage:
    python tools/sync_scenarios.py [DIR_OR_FILE]...

Defaults to ``DIVIDE_SCENARIOS_DIR`` from env, or
``./examples/scenarios/`` if not set.

The tool runs ``alembic upgrade head`` against ``DIVIDE_DB_URL`` first,
so a fresh Postgres / SQLite is usable out of the box.

Exit codes:
    0  all YAMLs synced (created/updated/unchanged) or none found
    1  one or more YAMLs were skipped (validation error)
    2  usage / IO error
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.db.session import get_sessionmaker  # noqa: E402
from app.services.scenario_sync import SyncReport, sync_files  # noqa: E402


def _ensure_schema() -> None:
    """Run alembic upgrade head so the scenarios table exists."""
    db_url = os.environ.get("DIVIDE_DB_URL")
    if not db_url:
        print("error: DIVIDE_DB_URL is required", file=sys.stderr)
        sys.exit(2)
    # Strip async driver so alembic uses a sync engine.
    sync_url = db_url.replace("+asyncpg", "").replace("+aiosqlite", "")
    # Run alembic from the repo root so relative DB paths like
    # ``sqlite:///./foo.db`` resolve the same way they do for the CLI's
    # own SQLAlchemy calls.
    api_dir = ROOT / "services" / "api"
    alembic_ini = api_dir / "alembic.ini"
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(alembic_ini), "upgrade", "head"],
        capture_output=True,
        text=True,
        env={**os.environ, "DIVIDE_DB_URL": sync_url, "PYTHONPATH": str(api_dir)},
        cwd=ROOT,
    )
    if r.returncode != 0:
        print(f"alembic upgrade head failed (exit={r.returncode}):\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}", file=sys.stderr)
        sys.exit(2)


async def _run(paths: list[Path], archive_missing: bool) -> "SyncReport":
    sm = get_sessionmaker()
    async with sm() as session:
        return await sync_files(session, paths, archive_missing=archive_missing)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Scenario YAML files or directories (default: $DIVIDE_SCENARIOS_DIR or ./examples/scenarios).",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Do not archive scenarios whose YAML is missing on disk.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the SyncReport as JSON and exit.",
    )
    args = parser.parse_args(argv)

    _ensure_schema()

    if args.inputs:
        paths = list(args.inputs)
    else:
        env_dir = os.environ.get("DIVIDE_SCENARIOS_DIR")
        if env_dir:
            paths = [Path(env_dir)]
        else:
            paths = [ROOT / "examples" / "scenarios"]

    for p in paths:
        if not p.exists():
            print(f"error: {p} does not exist", file=sys.stderr)
            return 2

    report = asyncio.run(
        _run(paths, archive_missing=not args.no_archive)
    )

    if args.json:
        import json
        json.dump(report.as_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print(f"created:   {len(report.created)}")
        print(f"updated:   {len(report.updated)}")
        print(f"unchanged: {len(report.unchanged)}")
        print(f"skipped:   {len(report.skipped)}")
        print(f"archived:  {len(report.archived)}")
        if report.skipped:
            print("\nskipped (validation errors):")
            for u in report.skipped:
                print(f"  - {u.source_path}: {u.error}")

    if report.skipped:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
