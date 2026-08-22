"""Tests for the scenario sync service.

We do NOT need a real DB here: SQLite-in-memory is enough to exercise
the upsert/archive logic. The JSON Schema is shared with the live app,
so we test against the actual ``schemas/scenario.schema.json``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import models
from app.db.base import Base
from app.services.scenario_sync import (
    SyncReport,
    collect_yaml_files,
    sync_files,
)


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    import asyncio
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


def _write(tmp_path: Path, name: str, body: dict) -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(body))
    return p


def _valid_scenario(name: str = "demo", **overrides) -> dict:
    """Produce a scenario YAML that passes schema validation.

    Schema requires ``spec`` to include: objectives, assets, networks,
    telemetry, scoring, win_conditions, artifacts. We provide minimal
    valid defaults and let callers override individual leaves.
    """
    body = {
        "apiVersion": "divide/v1",
        "kind": "Scenario",
        "metadata": {
            "name": name,
            "title": f"{name} title",
            "version": 1,
            "difficulty": "beginner",
            "duration_min": 30,
            "tags": ["test"],
        },
        "spec": {
            "objectives": {
                "red": ["Compromise a workstation."],
                "blue": ["Detect lateral movement within 10 minutes."],
            },
            "networks": [
                {"name": "corp", "cidr": "10.10.0.0/16"},
            ],
            "assets": [
                {
                    "role": "red_attacker",
                    "kind": "vm",
                    "template": "tpl-x",
                    "networks": ["corp"],
                }
            ],
            "telemetry": {
                "sinks": [{"type": "minio", "bucket": "divide-runs"}],
            },
            "scoring": {
                "blue": {"rules": [{"id": "detect_lateral", "weight": 10}], "pass_threshold": 5},
                "red": {"rules": [{"id": "exfil", "weight": 10}], "pass_threshold": 5},
            },
            "win_conditions": {
                "red": ["asset.ran_command:whoami on red_attacker"],
                "blue": ["alert.fired:lateral_movement on corp"],
            },
            "artifacts": {"sink_to": "minio", "bucket": "divide-runs", "retention_days": 14},
        },
    }
    body["metadata"].update(overrides.pop("metadata", {}))
    body["spec"].update(overrides.pop("spec", {}))
    body["spec"]["assets"][0].update(overrides.pop("asset", {}))
    return body


# --- collect_yaml_files ----------------------------------------------------


def test_collect_yaml_files_recursive(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.scenario.yaml").write_text("---")
    (tmp_path / "a" / "y.scenario.yml").write_text("---")
    (tmp_path / "a" / "z.yaml").write_text("---")  # not .scenario.yaml -> ignored
    files = collect_yaml_files([tmp_path])
    assert len(files) == 2
    assert all(f.name.startswith(("x", "y")) for f in files)


def test_collect_yaml_files_single_file(tmp_path: Path) -> None:
    p = tmp_path / "single.scenario.yaml"
    p.write_text("---")
    assert collect_yaml_files([p]) == [p]


# --- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_creates_new_scenario(tmp_path: Path, session: AsyncSession) -> None:
    yaml_path = _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))

    report = await sync_files(session, [tmp_path])
    assert isinstance(report, SyncReport)
    assert len(report.created) == 1
    assert len(report.unchanged) == 0
    assert report.created[0].name == "demo"
    assert report.created[0].scenario_id is not None

    row = (
        await session.execute(select(models.Scenario))
    ).scalar_one()
    assert row.name == "demo"
    assert row.archived_at is None
    assert row.spec["apiVersion"] == "divide/v1"


@pytest.mark.asyncio
async def test_sync_unchanged_on_repeat(tmp_path: Path, session: AsyncSession) -> None:
    yaml_path = _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))

    first = await sync_files(session, [tmp_path])
    second = await sync_files(session, [tmp_path])

    assert len(first.created) == 1
    assert len(second.unchanged) == 1
    assert len(second.created) == 0
    assert len(second.updated) == 0


@pytest.mark.asyncio
async def test_sync_updates_on_metadata_change(tmp_path: Path, session: AsyncSession) -> None:
    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo", metadata={"version": 1}))
    await sync_files(session, [tmp_path])

    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo", metadata={"version": 2}))
    second = await sync_files(session, [tmp_path])

    assert len(second.updated) == 1
    row = (await session.execute(select(models.Scenario))).scalar_one()
    assert row.version == 2


@pytest.mark.asyncio
async def test_sync_skips_invalid_yaml(tmp_path: Path, session: AsyncSession) -> None:
    bad = tmp_path / "bad.scenario.yaml"
    bad.write_text(yaml.safe_dump({"metadata": {"name": "x"}}))  # not a valid Scenario

    report = await sync_files(session, [tmp_path])
    assert len(report.skipped) == 1
    assert len(report.created) == 0
    # DB is empty.
    rows = (await session.execute(select(models.Scenario))).all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_sync_skips_malformed_yaml(tmp_path: Path, session: AsyncSession) -> None:
    bad = tmp_path / "garbage.scenario.yaml"
    bad.write_text("this: is: not: yaml: at: all: : :\n  - [unbalanced")

    report = await sync_files(session, [tmp_path])
    assert len(report.skipped) == 1
    assert "yaml" in (report.skipped[0].error or "").lower()


@pytest.mark.asyncio
async def test_sync_partial_failure_keeps_other_scenarios(
    tmp_path: Path, session: AsyncSession
) -> None:
    _write(tmp_path, "good.scenario.yaml", _valid_scenario("good"))
    bad = tmp_path / "bad.scenario.yaml"
    bad.write_text(yaml.safe_dump({"metadata": {"name": "bad"}}))

    report = await sync_files(session, [tmp_path])

    assert len(report.created) == 1
    assert len(report.skipped) == 1
    rows = (await session.execute(select(models.Scenario))).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "good"


@pytest.mark.asyncio
async def test_sync_archives_missing_yaml(tmp_path: Path, session: AsyncSession) -> None:
    """When a YAML disappears from disk, the row is archived, not deleted."""
    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))
    first = await sync_files(session, [tmp_path])
    assert len(first.created) == 1
    assert len(first.archived) == 0

    # Remove the YAML.
    (tmp_path / "demo.scenario.yaml").unlink()

    second = await sync_files(session, [tmp_path])
    assert second.archived == ["demo"]

    row = (await session.execute(select(models.Scenario))).scalar_one()
    assert row.archived_at is not None
    assert row.name == "demo"  # not deleted


@pytest.mark.asyncio
async def test_sync_archive_missing_disabled(
    tmp_path: Path, session: AsyncSession
) -> None:
    """With archive_missing=False, the row stays even when YAML is gone."""
    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))
    await sync_files(session, [tmp_path])

    (tmp_path / "demo.scenario.yaml").unlink()

    report = await sync_files(session, [tmp_path], archive_missing=False)
    assert report.archived == []
    row = (await session.execute(select(models.Scenario))).scalar_one()
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_sync_restores_archived_when_yaml_returns(
    tmp_path: Path, session: AsyncSession
) -> None:
    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))
    await sync_files(session, [tmp_path])

    (tmp_path / "demo.scenario.yaml").unlink()
    await sync_files(session, [tmp_path])  # archives

    _write(tmp_path, "demo.scenario.yaml", _valid_scenario("demo"))
    third = await sync_files(session, [tmp_path])

    assert third.archived == []
    row = (await session.execute(select(models.Scenario))).scalar_one()
    assert row.archived_at is None


@pytest.mark.asyncio
async def test_sync_multiple_dirs(tmp_path: Path, session: AsyncSession) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write(a, "one.scenario.yaml", _valid_scenario("one"))
    _write(b, "two.scenario.yaml", _valid_scenario("two"))

    report = await sync_files(session, [a, b])
    assert {r.name for r in report.created} == {"one", "two"}


@pytest.mark.asyncio
async def test_sync_multi_scenario_creates_rows(tmp_path: Path, session: AsyncSession) -> None:
    """Two YAMLs in one dir -> two rows in the DB."""
    _write(tmp_path, "alpha.scenario.yaml", _valid_scenario("alpha"))
    _write(tmp_path, "beta.scenario.yaml", _valid_scenario("beta"))

    report = await sync_files(session, [tmp_path])
    assert len(report.created) == 2
    rows = (await session.execute(select(models.Scenario))).scalars().all()
    assert sorted(r.name for r in rows) == ["alpha", "beta"]


# --- report shape ---------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_report_as_dict(tmp_path: Path, session: AsyncSession) -> None:
    _write(tmp_path, "alpha.scenario.yaml", _valid_scenario("alpha"))
    report = await sync_files(session, [tmp_path])
    d = report.as_dict()
    assert d["total"] == 1
    assert len(d["created"]) == 1
    assert d["created"][0]["name"] == "alpha"


# --- select import ---------------------------------------------------------


def test_select_models() -> None:
    """Sanity: select import works."""
    from sqlalchemy import select  # noqa


# --- schema resolution -----------------------------------------------------


def test_find_schema_in_dev_layout() -> None:
    """In the dev layout (running pytest from the repo root), the dev
    candidate wins. We just check it returns a file that exists."""
    from app.services.scenario_sync import _find_schema

    p = _find_schema()
    assert p.is_file()
    assert p.name == "scenario.schema.json"


def test_find_schema_with_env_override(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "custom.schema.json"
    fake.write_text('{"type": "object"}')
    monkeypatch.setenv("DIVIDE_SCENARIO_SCHEMA", str(fake))
    from app.services.scenario_sync import _find_schema

    assert _find_schema() == fake


def test_find_schema_falls_back_to_container_layout(tmp_path, monkeypatch) -> None:
    """If neither the dev layout nor the env var is available, the
    container layout should win. We lay out a fake repo that mirrors
    the container structure: file at depth 3, schema at parents[2]."""
    fake_file = tmp_path / "services" / "api" / "scenario_sync.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    # Container layout: parents[2] is `tmp_path/services/api`; put schema there.
    schema_in_container_layout = fake_file.parents[2] / "schemas" / "scenario.schema.json"
    schema_in_container_layout.parent.mkdir(parents=True)
    schema_in_container_layout.write_text('{"type": "object"}')
    monkeypatch.setenv("DIVIDE_SCENARIO_SCHEMA", "/nope.schema.json")

    import app.services.scenario_sync as sync_mod

    monkeypatch.setattr(sync_mod, "__file__", str(fake_file))

    found = sync_mod._find_schema()
    assert found == schema_in_container_layout
    assert found.is_file()
