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
    # F6: nullable so single-team runs (legacy) still work. An
    # Exercise-owned Run has exercise_id populated + a team name
    # (red / blue / white).
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="SET NULL"),
        nullable=True,
    )
    # F7: optional template this run was spawned from. When set,
    # the template's ``snapshot`` JSON describes the desired end
    # state (assets, flags, networks) -- used by /drills/{id}/reset.
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # F6: nullable for backward compat. Defaults to "red" so
    # legacy single-team runs continue to attribute flag
    # submissions to the red team.
    team: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default="red"
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
    exercise: Mapped["Exercise | None"] = relationship(
        back_populates="runs"
    )
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


# --- F6 multi-team: Exercise + Team + TeamMembership --------------------


class ExerciseStatus(str, enum.Enum):
    """Lifecycle for an Exercise (the F6 multi-team coordinator).

    A single-team Run (no Exercise) bypasses this entire state
    machine -- F5 and earlier work is unchanged.

    An Exercise moves through:

        idle  -- created; teams registered; no runs started
        live  -- runs are active; flags can be captured
        ended -- all runs are terminal; leaderboard frozen
        archived -- admin-only frozen snapshot (post-mortem)

    Transitions are validated in ``Exercise.transition_to`` so
    the FSM lives in one place and the unit tests can pin every
    valid transition.
    """

    IDLE = "idle"
    LIVE = "live"
    ENDED = "ended"
    ARCHIVED = "archived"

    @classmethod
    def can_transition(cls, src: "ExerciseStatus", dst: "ExerciseStatus") -> bool:
        """Return True iff ``src -> dst`` is a valid transition.

        Frozen transitions:
          * Any state -> archived (admin only)
          * idle -> live (operator starts the exercise)
          * live -> ended (operator stops the exercise or it
            auto-ends at scheduled time)
          * ended -> live is allowed (re-open after a pause)
        """
        if dst is cls.ARCHIVED:
            return True  # any -> archived
        if src is cls.IDLE and dst is cls.LIVE:
            return True
        if src is cls.LIVE and dst is cls.ENDED:
            return True
        if src is cls.ENDED and dst is cls.LIVE:
            return True
        return False


class Exercise(Base, TimestampMixin):
    """A multi-team exercise (F6).

    An Exercise wraps one or more Runs against a shared
    scenario. The Runs are parallel -- red and blue (and
    optionally white) each get their own isolated VM set
    sharing the same underlying scenario YAML.

    Lifecycle:
      * created (status=IDLE)
      * admin/lead sets ``started_at``; auto-transitions to
        LIVE at that time, or immediately on demand.
      * admin/lead sets ``ended_at``; auto-transitions to
        ENDED, or ``stop_exercise`` flips it manually.
      * status=ARCHIVED for post-mortem snapshots; runs
        remain queryable as historical record.
    """

    __tablename__ = "exercises"
    __table_args__ = (
        Index("ix_exercises_status", "status"),
        Index("ix_exercises_starts_at", "starts_at"),
        Index("ix_exercises_scenario_id", "scenario_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ExerciseStatus] = mapped_column(
        Enum(
            ExerciseStatus,
            name="exercise_status",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=ExerciseStatus.IDLE,
    )
    # Optional wall-clock bounds. The scheduler flips status
    # IDLE -> LIVE at starts_at and LIVE -> ENDED at ends_at
    # (F3-prep-style background asyncio task).
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)

    scenario: Mapped[Scenario] = relationship()
    runs: Mapped[list[Run]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )
    teams: Mapped[list["Team"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
    )

    def transition_to(self, new_status: ExerciseStatus) -> None:
        """Move the exercise to a new state; raises on invalid.

        Kept in one place so unit tests can cover every valid
        transition.
        """
        if not ExerciseStatus.can_transition(self.status, new_status):
            raise ValueError(
                f"cannot transition exercise {self.id} from "
                f"{self.status.value} to {new_status.value}"
            )
        self.status = new_status


class Team(Base, TimestampMixin):
    """A team within an Exercise.

    Teams are scoped to a single Exercise -- two teams across
    different exercises are not considered "the same team".
    Membership (who is on what team) is in TeamMembership.
    """

    __tablename__ = "teams"
    __table_args__ = (
        # A team name is unique within an exercise; same name
        # in a different exercise is allowed.
        Index("uq_teams_exercise_name", "exercise_id", "name", unique=True),
        Index("ix_teams_color", "color"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # A short hex color used for the LeaderboardCard bars.
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#888888")
    # Initial aggregate score for the team across all submitted
    # flags. Recomputed whenever a flag is captured via the
    # F5 endpoint (the existing flag-side logic didn't know
    # about teams; F6 updates it so the leaderboard reflects
    # per-team totals).
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    exercise: Mapped[Exercise] = relationship(back_populates="teams")
    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )


class TeamRole(str, enum.Enum):
    """The role a user plays on a team within an exercise.

    Caps at two values for F6:
      * ``operator`` -- the team lead; can cancel runs for their
        team.
      * ``member`` -- regular player.

    Admin/lead users can act on any team's exercise regardless
    of their team membership.
    """

    OPERATOR = "operator"
    MEMBER = "member"


class TeamMembership(Base, TimestampMixin):
    """A link between a User and a Team.

    One user can be on multiple teams across exercises (because
    exercises are independent), but at most one team per
    exercise. The unique constraint ``uq_team_membership_user_exercise``
    enforces that.
    """

    __tablename__ = "team_memberships"
    __table_args__ = (
        Index(
            "uq_team_membership_user_exercise",
            "sub", "exercise_id",
            unique=True,
        ),
        Index("ix_team_membership_team_id", "team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub: Mapped[str] = mapped_column(String(64), nullable=False)
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[TeamRole] = mapped_column(
        Enum(
            TeamRole,
            name="team_role",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=TeamRole.MEMBER,
    )

    team: Mapped[Team] = relationship(back_populates="memberships")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TeamMembership sub={self.sub!r} team={self.team_id} "
            f"exercise={self.exercise_id} role={self.role.value}>"
        )


# --- F7 range templates: Template model ---------------------------------


class Template(Base, TimestampMixin):
    """A reusable, immutable snapshot of an ended Run.

    Templates let operators:

      * Replay a drill with identical assets / flags / networks
        without re-typing the scenario YAML.
      * Hand a working state to a peer range (port + clone).
      * Train against a known-good configuration.

    Lifecycle:
      * Created from a SUCCEEDED Run (admin POST /templates).
      * Read-only once persisted: ``snapshot`` is a JSONB blob;
        we never update it (no PATCH endpoint). If you need a
        different snapshot, create a new template.
      * Deletable by admin only; cascades to NULL on Run FK.

    Snapshot contents:
      * ``scenario_id``: int (the scenario the source run used).
      * ``assets``: list[dict] -- frozen asset state (role, kind,
        template, networks).
      * ``flags``: list[dict] -- the planted flags at run-end.
      * ``networks``: list[dict] -- network topology.
      * ``scoring``: dict -- red/blue scoring rules.
    """

    __tablename__ = "templates"
    __table_args__ = (
        Index("ix_templates_scenario_id", "scenario_id"),
        Index("ix_templates_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Source run this template was created from. Nullable so we
    # can author a template by hand (future use case).
    from_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The scenario this template plays against. Always populated.
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Template id={self.id} name={self.name!r}>"


# --- F8 SOC view: TelemetryEvent ---------------------------------------


class TelemetrySeverity(str, enum.Enum):
    """Severity bucket for a TelemetryEvent.

    Kept intentionally coarse (4 buckets) -- operators filter
    on these in the SOC view, and a fine-grained 8-level scale
    would be visual noise. F8.5 can refine if needed.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def can_transition(cls, src: "TelemetrySeverity", dst: "TelemetrySeverity") -> bool:
        # No FSM here -- severity is a tag, not a state.
        return True


class TelemetryEvent(Base, TimestampMixin):
    """A persisted event from a Run.

    Sources of events:
      * Runner emits run.* events (started, completed, failed,
        cancelled).
      * Asset lifecycle emits asset.* events (cloned, booting,
        running, stopped, failed).
      * Flag-capture emits flag.* events (captured, rejected,
        expired).
      * Manual injection via ``POST /runs/{id}/events`` (admin /
        lead only) lets an operator surface a custom kill-chain
        signal -- e.g. "blue team noticed port 22 bruteforce".

    Lifecycle:
      * Rows are append-only. We never UPDATE TelemetryEvent
        rows; corrections go through a new "amended" event.
      * Soft-pruning via a future retention job (L2 2.14):
        a 24-hour TTL by default, configurable per run.
      * The live SSE endpoint (``/runs/{id}/events/stream``)
        tails the EventBus (in-process), not the DB. Recent
        events come from the DB on cold-connect.
    """

    __tablename__ = "telemetry_events"
    __table_args__ = (
        Index("ix_telemetry_run_id_ts", "run_id", "ts"),
        Index("ix_telemetry_kind", "kind"),
        Index("ix_telemetry_severity", "severity"),
        Index("ix_telemetry_source", "source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # FK to Run. SET NULL on Run delete so audit trail survives
    # drill deletion (cheap, helps the SOC view recover).
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK to Asset. SET NULL on Asset delete (F8 follows the
    # asset as a logical "device" -- when the VM is reaped, the
    # event still describes the historical fact).
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Event time. NOT created_at (which is when the row hit the
    # DB); ``ts`` is when the event happened at the source.
    # Backfilled in Python from ``time.time()`` if the source
    # doesn't supply it.
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[TelemetrySeverity] = mapped_column(
        Enum(
            TelemetrySeverity,
            name="telemetry_severity",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=TelemetrySeverity.INFO,
    )
    # Free-form payload (event-specific data). JSONB on Postgres,
    # TEXT on sqlite.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TelemetryEvent id={self.id} run={self.run_id} "
            f"kind={self.kind!r} severity={self.severity.value}>"
        )
