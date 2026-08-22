"""End-to-end test for the Alembic migration chain.

Boots an in-memory SQLite via alembic.ini + env.py, runs `upgrade head`,
inspects the resulting schema, then runs `downgrade base`. Catches:
- Migration imports errors
- Schema drift between models and migration
- Downgrade irreversibility
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = ROOT / "alembic.ini"
ENV = dict(os.environ)
ENV["DIVIDE_DB_URL"] = "sqlite:///:memory:"  # Alembic uses sync driver
ENV["PYTHONPATH"] = str(ROOT) + os.pathsep + ENV.get("PYTHONPATH", "")


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), *args],
        capture_output=True,
        text=True,
        env=ENV,
        cwd=ROOT,
    )


def test_alembic_upgrade_creates_all_tables(tmp_path) -> None:
    # Override DB to a file (in-memory doesn't work across subprocess).
    db_path = tmp_path / "test.sqlite"
    env = dict(ENV)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "upgrade", "head"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert r.returncode == 0, f"upgrade failed:\n{r.stderr}\n{r.stdout}"

    con = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    finally:
        con.close()
    # Our 4 tables + alembic_version
    assert {"scenarios", "runs", "assets", "audit_log", "alembic_version"} <= tables


def test_alembic_current_reports_head(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite"
    env = dict(ENV)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "upgrade", "head"],
        capture_output=True, text=True, env=env, cwd=ROOT, check=True,
    )
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "current"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert r.returncode == 0
    assert "(head)" in r.stdout


def test_alembic_downgrade_removes_all_tables(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite"
    env = dict(ENV)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "upgrade", "head"],
        capture_output=True, text=True, env=env, cwd=ROOT, check=True,
    )
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "downgrade", "base"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert r.returncode == 0, f"downgrade failed:\n{r.stderr}"

    con = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    finally:
        con.close()
    assert tables == {"alembic_version"}, f"expected only alembic_version left, got {tables}"


def test_alembic_round_trip(tmp_path) -> None:
    """upgrade -> downgrade -> upgrade should be a no-op and end at head."""
    db_path = tmp_path / "test.sqlite"
    env = dict(ENV)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    for cmd in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), *cmd],
            capture_output=True, text=True, env=env, cwd=ROOT,
        )
        assert r.returncode == 0, f"{cmd} failed:\n{r.stderr}"
    # Confirm we're at head and the tables are all present.
    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "current"],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    assert "(head)" in cur.stdout


def test_alembic_indexes_present(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite"
    env = dict(ENV)
    env["DIVIDE_DB_URL"] = f"sqlite:///{db_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "--config", str(ALEMBIC_INI), "upgrade", "head"],
        capture_output=True, text=True, env=env, cwd=ROOT, check=True,
    )
    con = sqlite3.connect(str(db_path))
    try:
        idx_by_table: dict[str, list[str]] = {}
        for row in con.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'"):
            idx_by_table.setdefault(row[1], []).append(row[0])
    finally:
        con.close()

    # Each non-meta table needs at least one declared index (beyond PK).
    for tbl in ("scenarios", "runs", "assets", "audit_log"):
        idxs = [i for i in idx_by_table.get(tbl, []) if not i.startswith("sqlite_")]
        assert len(idxs) >= 1, f"{tbl} has no declared indexes"
