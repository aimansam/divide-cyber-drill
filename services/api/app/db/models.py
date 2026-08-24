"""ORM models for div:ide.

Design notes
------------
- The authoritative definition of *what* a scenario is lives in YAML files
  (schemas/scenario.schema.json). The ``Scenario`` table mirrors enough of
  that to support listing, search, and version bookkeeping. Re-importing a
  YAML bumps ``version`` and ``spec`` (jsonb).
- A ``Run`` is one execution of a ``Scenario``. It owns ``Asset`` rows for
  every VM it spawns, and an ``AuditLog`` entry at each lifecycle event.
- We deliberately do NOT model telemetry events here. Volume is unbounded;
  they live in OpenSearch/Wazuh. The DB records only control-plane events.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

# --- enums ------------------------------------------------------------------


class RunStatus(str, enum.Enum):
    """Lifecycle states for a drill Run.

    Transitions:
        pending -> running -> (succeeded | failed | timeout | cancelled)
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AssetStatus(str, enum.Enum):
    """Per-asset lifecycle within a Run."""

    PLANNED = "planned"
    CLONING = "cloning"
    BOOTING = "booting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    ORPHANED = "orphaned"  # left running after run ended; needs manual cleanup


class AuditAction(str, enum.Enum):
    """Append-only audit log action codes."""

    SCENARIO_CREATED = "scenario.created"
    SCENARIO_UPDATED = "scenario.updated"
    SCENARIO_DELETED = "scenario.deleted"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMEOUT = "run.timeout"  # auto-cancelled by the watchdog (L2 2.8)
    ASSET_SPAWNED = "asset.spawned"
    ASSET_FAILED = "asset.failed"
    ASSET_ORPHANED = "asset.orphaned"
    # F5: runner logged the planting intent for a flag
    # declared in spec.flags[]. The actual filesystem write
    # happens via cloud-init user_data (see docs/F5-SCORING.md);
    # the audit row is the operator-visible record.
    FLAG_PLANTED = "flag.planted"


# --- Scenario ---------------------------------------------------------------


class Scenario(Base, TimestampMixin):
    """Catalog row for a Scenario YAML file.

    ``name`` matches the YAML ``metadata.name``. ``version`` is the YAML
    revision (incremented on each re-import of a breaking change). ``spec``
    is a jsonb blob of the validated YAML — the schema is still the source
    of truth, this column is for read performance and history.
    """

    __tablename__ = "scenarios"
    __table_args__ = (
        Index("ix_scenarios_difficulty", "difficulty"),
        Index("ix_scenarios_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Soft-delete flag: set when the YAML backing this row is removed from
    # disk. Historical Runs still reference this row via FK, so we never
    # hard-delete a scenario. Set to NULL to re-activate.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    runs: Mapped[list[Run]] = relationship(back_populates="scenario")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Scenario id={self.id} name={self.name!r} v{self.version}>"


# --- Run --------------------------------------------------------------------


class Run(Base, TimestampMixin):
    """One execution of a Scenario.

    The ``started_at`` / ``ended_at`` columns are independent of the mixin's
    timestamps so they can be set explicitly by the runner.
    """

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_scenario_id", "scenario_id"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            name="run_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=RunStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score_blue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_red: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    assets: Mapped[list[Asset]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    flag_submissions: Mapped[list["FlagSubmission"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    @property
    def duration_sec(self) -> int | None:
        if self.started_at is None or self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Run id={self.id} scenario_id={self.scenario_id} {self.status.value}>"


# --- Asset ------------------------------------------------------------------


class Asset(Base, TimestampMixin):
    """A single VM/clone spawned for a Run."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_run_id", "run_id"),
        Index("ix_assets_status", "status"),
        # NOTE: a previous schema (0001_initial_schema.py)
        # enforced (run_id, role) uniqueness. That constraint
        # silently capped ``spec.assets[].count`` at 1, since a
        # ``victim_workstation count: 2`` declaration tried to
        # insert two rows with the same role and hit a unique
        # violation. Migration 0004_asset_instance.py drops the
        # constraint so multi-instance assets work.
        # The runner now generates distinct role names per
        # instance: ``victim_workstation`` + ``_N`` (1-indexed)
        # when count > 1. Single-count assets keep the original
        # role name (no suffix).
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="vm")
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(
            AssetStatus,
            name="asset_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=AssetStatus.PLANNED,
    )
    pve_vmid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pve_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pve_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="assets")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Asset id={self.id} run_id={self.run_id} {self.role!r} {self.status.value}>"


# --- Flag (F5) ------------------------------------------------------


class FlagSide(str, enum.Enum):
    """Which side is hunting this flag.

    Red hunts blue-planted flags (typical CTF). Blue hunts
    red-planted flags (defender challenge). ``self`` flags are
    deployed on the team's own assets as proof-of-life.
    """

    RED = "red"
    BLUE = "blue"
    SELF = "self"


class FlagSubmission(Base, TimestampMixin):
    """One captured flag.

    A scenario declares ``spec.flags[]``: each entry has an
    id, a side (who hunts it), the planted value, the role of
    the asset it's planted on, a decay_window_seconds, and
    base points. The runner plants the value on the asset
    during provisioning (typically baked into the asset's
    filesystem via cloud-init user_data).

    A team captures a flag by submitting its value via
    ``POST /api/v1/drills/{id}/submit-flag``. The server:

      * validates the (run, flag_id, value) tuple,
      * records this FlagSubmission row with the team's role +
        capture time,
      * computes points via time-decay scoring.
    """

    __tablename__ = "flag_submissions"
    __table_args__ = (
        Index("ix_flag_submissions_run_id", "run_id"),
        Index("ix_flag_submissions_team", "team"),
        # One submission per (run, flag, team).
        Index(
            "uq_flag_submissions_run_flag_team",
            "run_id",
            "flag_id",
            "team",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    flag_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team: Mapped[str] = mapped_column(String(16), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    # Captured-at is the moment the server validated the flag.
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Frozen so re-grading a scoring rule later doesn't rewrite
    # historical scores.
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="flag_submissions")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FlagSubmission id={self.id} run={self.run_id} "
            f"flag={self.flag_id!r} team={self.team!r} +{self.points}>"
        )


# --- User -------------------------------------------------------------------


class User(Base, TimestampMixin):
    """A login-capable div:ide user (F3-prep credential login).

    Replaces the bare ``tools/issue_token.py`` paste-your-token UX
    with a real username + password flow. The token issued by
    ``POST /api/v1/auth/login`` is the same HMAC-SHA256 token the
    paste flow emits — :mod:`app.core.auth` doesn't care how the
    caller got the token, only that it verifies.

    Why a separate ``User`` table and not just another ``AuditLog``
    actor name:

      * Password storage needs an argon2 hash column. Audit rows are
        append-only and don't carry secret material.
      * ``disabled`` lets an admin disable an account without
        deleting its history (audit still names the user).
      * ``last_login_at`` is operational telemetry, not audit, and
        belongs on the user record.

    Bootstrap: on API startup, if ``DIVIDE_BOOTSTRAP_ADMIN_SUB`` +
    ``DIVIDE_BOOTSTRAP_ADMIN_PASSWORD`` env vars are set AND no
    admin exists, the user is created. The env-var path is the
    only way to seed the first admin without a manual
    ``divide create-user`` invocation. Subsequent admins are
    added through ``POST /api/v1/admin/users`` (future L3 work) or
    via the bootstrap-env-var override by removing the first
    admin and re-bootstrapping.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_disabled", "disabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ``sub`` is the username that goes into the token. Unique so a
    # second ``create_user`` raises IntegrityError (caller can
    # decide whether to surface that as 409). Trimmed of leading /
    # trailing whitespace; caller is responsible for lower-casing
    # if the deployment cares.
    sub: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Argon2id PHC string (``$argon2id$v=19$m=...,t=...,p=...$salt$hash``).
    # Never log this; never return it from a router. ``verify_password``
    # in :mod:`app.services.users` is the only legitimate reader.
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # Free-form role string. We don't FK into an enum table — the
    # canonical list lives on :class:`app.core.auth.Role` and is
    # enforced at write time by :func:`app.services.users.create_user`.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Admin kill switch. ``disabled=True`` users get 401 on
    # ``POST /auth/login``; their existing tokens still verify
    # until ``exp`` (consistent with the rest of the auth model —
    # no revocation list yet).
    disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} sub={self.sub!r} role={self.role!r}>"


# --- AuditLog ---------------------------------------------------------------


class AuditLog(Base):
    """Append-only event log. No updates, no deletes."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_at", "at"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_actor", "actor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(
            AuditAction,
            name="audit_action",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False
    )
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Optional polymorphic links. Both nullable; the combination lets us
    # log any control-plane event without forcing every entity into the DB.
    scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog id={self.id} {self.action.value!r}>"


__all__ = [
    "AuditAction",
    "Asset",
    "AssetStatus",
    "AuditLog",
    "Base",
    "Run",
    "RunStatus",
    "Scenario",
    "TimestampMixin",
    "User",
]
