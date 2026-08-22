"""Scenario sync: YAML files -> DB rows.

This is the bridge between the on-disk scenario catalog and the
DB. The repo is the source of truth (YAML + JSON Schema), but the
runner reads from the DB. The sync keeps the two in agreement.

Lifecycle
---------
1. ``collect_yaml_files`` walks one or more directories and returns
   the YAML files that look like divide scenarios.
2. ``sync_files`` validates each against the schema, then upserts a
   Scenario row keyed by ``metadata.name``. Re-running on an unchanged
   YAML is a no-op (the row is updated in place with no schema bump).
3. ``SyncReport`` summarises the result so callers (CLI, lifespan,
   /readyz) can report what happened.

Design choices
--------------
- Schema validation failure on a single YAML is logged and skipped;
  the sync does not abort. CI catches bad YAML before deploy.
- The ``Scenario.name`` column is unique, so the upsert is
  "SELECT FOR UPDATE -> INSERT or UPDATE".
- ``archived_at`` is set automatically when a YAML that used to
  exist is no longer present on disk; admins can re-activate by
  removing the timestamp via ``POST /api/v1/scenarios/{name}/restore``.
- We do not delete history: even an "archived" scenario still has
  linked Runs that we must preserve for after-action reports.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models

log = logging.getLogger(__name__)

SCHEMA_PATH: Path | None = None  # legacy; resolved lazily via _find_schema().


def _find_schema() -> Path:
    """Locate ``schemas/scenario.schema.json`` for both dev and container.

    Resolution order:
      1. ``DIVIDE_SCENARIO_SCHEMA`` env var (explicit override)
      2. ``services/api/schemas/scenario.schema.json`` (container layout,
         2 parents up from this file)
      3. ``<repo_root>/schemas/scenario.schema.json`` (dev layout,
         4 parents up from this file)
    """
    env_path = os.environ.get("DIVIDE_SCENARIO_SCHEMA")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
    file = Path(__file__).resolve()
    candidates: list[Path] = []
    for depth in (2, 4):
        try:
            parent = file.parents[depth]
        except IndexError:
            continue
        candidates.append(parent / "schemas" / "scenario.schema.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "scenario.schema.json not found; tried:\n  "
        + "\n  ".join(str(c) for c in [env_path, *candidates])
    )


# ---------------------------------------------------------------------------
# format checker (shared with tools/validate_scenario.py)
# ---------------------------------------------------------------------------

_format_checker = FormatChecker()


@_format_checker.checks("cidr", raises=ValueError)
def _check_cidr(value: object) -> bool:
    import ipaddress
    if not isinstance(value, str):
        return True
    ipaddress.ip_network(value, strict=False)
    return True


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------


@dataclass
class ScenarioUpsert:
    """One YAML -> DB outcome."""

    source_path: Path
    name: str | None
    action: str  # "created" | "updated" | "unchanged" | "skipped"
    error: str | None = None
    scenario_id: int | None = None


@dataclass
class SyncReport:
    """Whole-run summary."""

    created: list[ScenarioUpsert] = field(default_factory=list)
    updated: list[ScenarioUpsert] = field(default_factory=list)
    unchanged: list[ScenarioUpsert] = field(default_factory=list)
    skipped: list[ScenarioUpsert] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)  # names

    @property
    def total(self) -> int:
        return (
            len(self.created)
            + len(self.updated)
            + len(self.unchanged)
            + len(self.skipped)
            + len(self.archived)
        )

    @property
    def ok(self) -> bool:
        """True iff every YAML was either upserted or unchanged."""
        return not self.skipped

    def as_dict(self) -> dict:
        return {
            "created": [self._row_to_dict(u) for u in self.created],
            "updated": [self._row_to_dict(u) for u in self.updated],
            "unchanged": [u.source_path for u in self.unchanged],
            "skipped": [self._row_to_dict(u) for u in self.skipped],
            "archived": self.archived,
            "total": self.total,
        }

    @staticmethod
    def _row_to_dict(u: ScenarioUpsert) -> dict:
        return {
            "source_path": str(u.source_path),
            "name": u.name,
            "action": u.action,
            "scenario_id": u.scenario_id,
            "error": u.error,
        }


# ---------------------------------------------------------------------------
# file collection
# ---------------------------------------------------------------------------


def collect_yaml_files(paths: Sequence[Path]) -> list[Path]:
    """Expand a list of files/directories into a sorted list of YAML paths."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.rglob("*.scenario.yaml")))
            out.extend(sorted(p.rglob("*.scenario.yml")))
        elif p.is_file():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------


def _load_validator() -> Draft202012Validator:
    with _find_schema().open(encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    return Draft202012Validator(schema, format_checker=_format_checker)


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _format_validation_error(err: ValidationError) -> str:
    path = "$" + "".join(
        f".{p}" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path
    )
    msg = err.message.splitlines()[0] if err.message else "validation error"
    return f"{path}: {msg}"


# ---------------------------------------------------------------------------
# the actual sync
# ---------------------------------------------------------------------------


async def sync_files(
    session: AsyncSession,
    paths: Iterable[Path],
    *,
    archive_missing: bool = True,
) -> SyncReport:
    """Upsert every YAML at ``paths`` into the ``scenarios`` table.

    If ``archive_missing`` is True, every ``scenarios`` row whose
    ``source_path`` is NOT present in any of the provided ``paths``
    gets ``archived_at`` set to the current time. We archive rather
    than delete so historical Runs keep their FK.

    Returns a ``SyncReport`` describing what happened.
    """
    validator = _load_validator()
    files = collect_yaml_files(list(paths))
    report = SyncReport()

    seen_source_paths: set[str] = set()
    seen_names: set[str] = set()

    for path in files:
        try:
            data = _load_yaml(path)
            errors = sorted(
                validator.iter_errors(data), key=lambda e: list(e.absolute_path)
            )
        except (yaml.YAMLError, OSError) as exc:
            log.warning("scenario_sync.parse_failed", extra={"file_path": str(path), "error": str(exc)})
            report.skipped.append(
                ScenarioUpsert(source_path=path, name=None, action="skipped", error=str(exc))
            )
            continue

        if errors:
            log.warning(
                "scenario_sync.invalid",
                extra={
                    "file_path": str(path),
                    "errors": [_format_validation_error(e) for e in errors],
                },
            )
            report.skipped.append(
                ScenarioUpsert(
                    source_path=path,
                    name=None,
                    action="skipped",
                    error="; ".join(_format_validation_error(e) for e in errors),
                )
            )
            continue

        upsert = await _upsert_one(session, path, data)
        seen_source_paths.add(str(path.resolve()))
        if upsert.name:
            seen_names.add(upsert.name)
        if upsert.action == "created":
            report.created.append(upsert)
        elif upsert.action == "updated":
            report.updated.append(upsert)
        else:
            report.unchanged.append(upsert)

    if archive_missing:
        await _archive_missing(
            session,
            seen_source_paths=seen_source_paths,
            seen_names=seen_names,
            report=report,
        )

    await session.commit()
    return report


async def _upsert_one(
    session: AsyncSession, path: Path, data: dict
) -> ScenarioUpsert:
    metadata = data.get("metadata") or {}
    name = metadata.get("name")
    if not name:
        return ScenarioUpsert(
            source_path=path, name=None, action="skipped", error="metadata.name missing"
        )

    existing = (
        await session.execute(select(models.Scenario).where(models.Scenario.name == name))
    ).scalar_one_or_none()

    spec_blob = data.get("spec") or {}
    new_payload = dict(
        title=metadata["title"],
        version=metadata["version"],
        difficulty=metadata["difficulty"],
        duration_min=metadata["duration_min"],
        tags=metadata.get("tags", []),
        authors=metadata.get("authors", []),
        spec=data,
        source_path=str(path),
    )

    if existing is None:
        row = models.Scenario(name=name, **new_payload)
        session.add(row)
        await session.flush()
        log.info("scenario_sync.created", extra={"scenario_name": name, "file_path": str(path)})
        return ScenarioUpsert(
            source_path=path,
            name=name,
            action="created",
            scenario_id=row.id,
        )

    # Update in place. Bump `updated_at` only if anything actually changed.
    changed = False
    for key, val in new_payload.items():
        if getattr(existing, key) != val:
            setattr(existing, key, val)
            changed = True
    # If the row was archived and the YAML is back, re-activate.
    if existing.archived_at is not None:
        existing.archived_at = None
        changed = True

    if changed:
        log.info("scenario_sync.updated", extra={"scenario_name": name, "file_path": str(path)})
        action = "updated"
    else:
        action = "unchanged"

    return ScenarioUpsert(
        source_path=path,
        name=name,
        action=action,
        scenario_id=existing.id,
    )


async def _archive_missing(
    session: AsyncSession,
    *,
    seen_source_paths: set[str],
    seen_names: set[str],
    report: SyncReport,
) -> None:
    """Mark every still-published scenario as archived if its source
    path is no longer present in the sync set."""
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(models.Scenario).where(models.Scenario.archived_at.is_(None))
        )
    ).scalars().all()
    for row in rows:
        # If we saw its source_path or its name, keep it.
        if row.name in seen_names:
            continue
        if row.source_path and row.source_path in seen_source_paths:
            continue
        row.archived_at = now
        report.archived.append(row.name)
        log.info(
            "scenario_sync.archived",
            extra={"scenario_name": row.name, "src_path": row.source_path},
        )
