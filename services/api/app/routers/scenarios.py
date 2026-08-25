"""Scenario catalog endpoints.

- ``GET  /api/v1/scenarios``         list active scenarios
- ``POST /api/v1/scenarios``         import a YAML (creates or updates)
- ``GET  /api/v1/scenarios/{name}``  get one scenario by name
- ``DELETE /api/v1/scenarios/{name}`` soft-delete (set archived_at)
- ``POST /api/v1/scenarios/{name}/restore`` un-archive
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import models as db_models
from app.db.session import get_session
from app.services.scenario_sync import (
    _format_checker,  # noqa: F401  -- shared with sync service
    _find_schema as _find_scenario_schema,
)

router = APIRouter()

# Validator instance, built once at import. Reused for every POST.
_validator: Draft202012Validator | None = None


def _get_validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        with _find_scenario_schema().open(encoding="utf-8") as f:
            schema = yaml.safe_load(f)
        _validator = Draft202012Validator(
            schema, format_checker=FormatChecker()
        )
    return _validator


# --- DTOs ------------------------------------------------------------------


def _row_to_dict(row: db_models.Scenario) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "title": row.title,
        "version": row.version,
        "difficulty": row.difficulty,
        "duration_min": row.duration_min,
        "tags": row.tags,
        "authors": row.authors,
        # F10.3: include the spec so the onboarding wizard can
        # detect multi-team scenarios (red + blue objectives)
        # without an N+1 fetch per row. The spec is a small JSON
        # blob (~1-5 KB) and the catalog rarely exceeds a few
        # dozen entries; the bandwidth cost is negligible.
        "spec": row.spec,
        "source_path": row.source_path,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# --- GET / -----------------------------------------------------------------


@router.get("", summary="List active scenarios")
async def list_scenarios(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict:
    q = select(db_models.Scenario)
    if not include_archived:
        q = q.where(db_models.Scenario.archived_at.is_(None))
    q = q.order_by(db_models.Scenario.name)
    rows = (await session.execute(q)).scalars().all()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": len(rows),
    }


@router.get("/{name}", summary="Get one scenario by name")
async def get_scenario(name: str, session: AsyncSession = Depends(get_session)) -> dict:
    row = (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {name!r} not found")
    return _row_to_dict(row)


# --- POST / ----------------------------------------------------------------


@router.post("", summary="Import a scenario YAML")
async def import_scenario(
    body: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Two accepted shapes:

    1. ``{"yaml": "<full YAML string>"}`` — body is parsed and validated.
    2. ``{"path": "relative/or/absolute/path.scenario.yaml"}`` — file is
       read from the configured ``scenarios_dir`` (or absolute).

    Returns the upserted row (200). 422 if YAML is malformed or fails the
    schema. 409 if metadata.name is missing.
    """
    if "yaml" in body:
        try:
            data = yaml.safe_load(body["yaml"])
        except yaml.YAMLError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"yaml parse error: {exc}",
            ) from exc
        source_path = body.get("source_path") or "<api>"
    elif "path" in body:
        requested = Path(body["path"])
        # Resolve relative paths against the configured scenarios dir.
        if not requested.is_absolute():
            requested = Path(settings.scenarios_dir) / requested
        if not requested.is_file():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"file not found: {requested}",
            )
        try:
            with requested.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"yaml parse error: {exc}",
            ) from exc
        source_path = str(requested)
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "body must include either `yaml` (string) or `path` (string)",
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "top-level YAML must be a mapping",
        )

    # Validate.
    errors = sorted(_get_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        msg = "; ".join(_format_validation_error(e) for e in errors)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)

    metadata = data.get("metadata") or {}
    name = metadata.get("name")
    if not name:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "scenario metadata.name is required",
        )

    row = (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.name == name)
        )
    ).scalar_one_or_none()

    payload = dict(
        title=metadata["title"],
        version=metadata["version"],
        difficulty=metadata["difficulty"],
        duration_min=metadata["duration_min"],
        tags=metadata.get("tags", []),
        authors=metadata.get("authors", []),
        spec=data,
        source_path=source_path,
    )

    if row is None:
        row = db_models.Scenario(name=name, **payload)
        session.add(row)
    else:
        for k, v in payload.items():
            setattr(row, k, v)
        row.archived_at = None  # re-import un-archives

    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row)


# --- DELETE / restore -------------------------------------------------------


@router.delete("/{name}", summary="Archive a scenario")
async def archive_scenario(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {name!r} not found")
    row.archived_at = datetime.now(timezone.utc)
    await session.commit()
    return {"name": row.name, "archived_at": row.archived_at.isoformat()}


@router.post("/{name}/restore", summary="Restore an archived scenario")
async def restore_scenario(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"scenario {name!r} not found")
    row.archived_at = None
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row)


# --- helpers ---------------------------------------------------------------


def _format_validation_error(err: ValidationError) -> str:
    path = "$" + "".join(
        f".{p}" if isinstance(p, str) else f"[{p}]" for p in err.absolute_path
    )
    msg = err.message.splitlines()[0] if err.message else "validation error"
    return f"{path}: {msg}"
