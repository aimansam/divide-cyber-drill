"""ORM models for OxBlood - Comprehensive 50-table schema.

This module defines SQLAlchemy models for all 50 tables in the OxBlood database,
organized into 10 modules:
1. User Management
2. Team Management
3. Lab Management
4. Drill Management
5. Submission System
6. Scoring System
7. Benchmarking System
8. Reporting System
9. Learning Path System
10. Admin & Audit System
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# ============================================================================
# ENUM TYPES
# ============================================================================

class UserRole(str, enum.Enum):
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    TEAM_LEADER = "team_leader"
    ADMINISTRATOR = "administrator"
    OBSERVER = "observer"


class LabStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class LabDifficulty(str, enum.Enum):
    BEGINNER = "beginner"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class DrillStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SubmissionStatus(str, enum.Enum):
    PENDING = "pending"
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    REVIEWED = "reviewed"


class ReportStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    GRADED = "graded"
    APPROVED = "approved"


class SeverityLevel(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class EvidenceType(str, enum.Enum):
    SCREENSHOT = "screenshot"
    COMMAND_OUTPUT = "command_output"
    LOG_EXCERPT = "log_excerpt"
    NETWORK_CAPTURE = "network_capture"
    FILE = "file"
    OTHER = "other"


class AuditAction(str, enum.Enum):
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    LAB_CREATED = "lab.created"
    LAB_UPDATED = "lab.updated"
    LAB_PUBLISHED = "lab.published"
    LAB_ARCHIVED = "lab.archived"
    DRILL_CREATED = "drill.created"
    DRILL_STARTED = "drill.started"
    DRILL_COMPLETED = "drill.completed"
    FLAG_SUBMITTED = "flag.submitted"
    FLAG_CORRECT = "flag.correct"
    FLAG_INCORRECT = "flag.incorrect"
    REPORT_CREATED = "report.created"
    REPORT_SUBMITTED = "report.submitted"
    REPORT_GRADED = "report.graded"
    TEAM_CREATED = "team.created"
    TEAM_UPDATED = "team.updated"
    TEAM_MEMBER_ADDED = "team.member_added"
    TEAM_MEMBER_REMOVED = "team.member_removed"
    SCORE_UPDATED = "score.updated"
    BENCHMARK_CALCULATED = "benchmark.calculated"
    ADMIN_ACTION = "admin.action"


class NotificationType(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    ACHIEVEMENT = "achievement"
    DEADLINE = "deadline"


class LearningPathStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"



# ============================================================================
# MODULE 1: USER MANAGEMENT
# ============================================================================

class User(Base):
    """Main user accounts table."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name='user_role', values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.STUDENT)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    profile: Mapped[Optional[UserProfile]] = relationship("UserProfile", back_populates="user", uselist=False)
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user")
    badges: Mapped[list[UserBadge]] = relationship("UserBadge", back_populates="user")
    activity_logs: Mapped[list[UserActivityLog]] = relationship("UserActivityLog", back_populates="user")

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
        Index("idx_users_role", "role"),
        Index("idx_users_active", "is_active", postgresql_where=text("deleted_at IS NULL")),
    )


class UserProfile(Base):
    """Extended user profile information."""
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500))
    organization: Mapped[Optional[str]] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    github_username: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    skills: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    interests: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="profile")


class Session(Base):
    """Active authentication sessions."""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    """Temporary tokens for password reset."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserActivityLog(Base):
    """Track user actions for analytics."""
    __tablename__ = "user_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[int]] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="activity_logs")


class Badge(Base):
    """Achievement badge definitions."""
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(String(50), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rarity: Mapped[str] = mapped_column(String(20), nullable=False, default="common")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserBadge(Base):
    """Track which badges each user has earned."""
    __tablename__ = "user_badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    badge_id: Mapped[int] = mapped_column(Integer, ForeignKey("badges.id", ondelete="CASCADE"), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="badges")
    badge: Mapped[Badge] = relationship("Badge")

    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badges"),
    )



# ============================================================================
# MODULE 2: TEAM MANAGEMENT
# ============================================================================

class Team(Base):
    """Team definitions for collaborative exercises."""
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    organization: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    members: Mapped[list[TeamMembership]] = relationship("TeamMembership", back_populates="team")
    invitations: Mapped[list[TeamInvitation]] = relationship("TeamInvitation", back_populates="team")

    __table_args__ = (
        Index("idx_teams_name", "name"),
        Index("idx_teams_active", "is_active", postgresql_where=text("deleted_at IS NULL")),
    )


class TeamMembership(Base):
    """Track which users belong to which teams."""
    __tablename__ = "team_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    team: Mapped[Team] = relationship("Team", back_populates="members")
    user: Mapped[User] = relationship("User")

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_memberships"),
    )


class TeamInvitation(Base):
    """Track team invitations sent to users."""
    __tablename__ = "team_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    invited_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invited_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    team: Mapped[Team] = relationship("Team", back_populates="invitations")


class TeamStatistic(Base):
    """Historical team performance data."""
    __tablename__ = "team_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="SET NULL"))
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flags_captured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objectives_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    rank_position: Mapped[Optional[int]] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================================
# MODULE 3: LAB MANAGEMENT
# ============================================================================

class LabCategory(Base):
    """Lab categories for organization."""
    __tablename__ = "lab_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lab_categories.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Tag(Base):
    """Tags for labeling labs."""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(7))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Lab(Base):
    """Training lab and scenario definitions."""
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lab_categories.id", ondelete="SET NULL"))
    difficulty: Mapped[LabDifficulty] = mapped_column(Enum(LabDifficulty, name='lab_difficulty', values_callable=lambda x: [e.value for e in x]), nullable=False, default=LabDifficulty.BEGINNER)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[LabStatus] = mapped_column(Enum(LabStatus, name='lab_status', values_callable=lambda x: [e.value for e in x]), nullable=False, default=LabStatus.DRAFT)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_team_size: Mapped[Optional[int]] = mapped_column(Integer)
    max_team_size: Mapped[Optional[int]] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    authors: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    prerequisites: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    learning_objectives: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    source_path: Mapped[Optional[str]] = mapped_column(String(500))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    flags: Mapped[list[LabFlag]] = relationship("LabFlag", back_populates="lab")
    objectives: Mapped[list[LabObjective]] = relationship("LabObjective", back_populates="lab")
    hints: Mapped[list[LabHint]] = relationship("LabHint", back_populates="lab")
    files: Mapped[list[LabFile]] = relationship("LabFile", back_populates="lab")
    tags: Mapped[list[Tag]] = relationship("Tag", secondary="lab_tags")

    __table_args__ = (
        Index("idx_labs_name", "name"),
        Index("idx_labs_category", "category_id"),
        Index("idx_labs_difficulty", "difficulty"),
        Index("idx_labs_status", "status"),
        Index("idx_labs_public", "is_public"),
    )


class LabTag(Base):
    """Many-to-many relationship between labs and tags."""
    __tablename__ = "lab_tags"

    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class TargetMachine(Base):
    """Target machines for labs."""
    __tablename__ = "target_machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    os_type: Mapped[str] = mapped_column(String(50), nullable=False)
    os_version: Mapped[Optional[str]] = mapped_column(String(50))
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    vulnerabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    services: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LabObjective(Base):
    """Learning objectives for labs."""
    __tablename__ = "lab_objectives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    lab: Mapped[Lab] = relationship("Lab", back_populates="objectives")


class LabFlag(Base):
    """Flags to be captured in labs."""
    __tablename__ = "lab_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    flag_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    hint: Mapped[Optional[str]] = mapped_column(Text)
    hint_penalty: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    decay_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    lab: Mapped[Lab] = relationship("Lab", back_populates="flags")

    __table_args__ = (
        UniqueConstraint("lab_id", "flag_id", name="uq_lab_flags"),
    )


class LabHint(Base):
    """Hints for lab objectives."""
    __tablename__ = "lab_hints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    objective_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lab_objectives.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    penalty_points: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    lab: Mapped[Lab] = relationship("Lab", back_populates="hints")


class LabFile(Base):
    """Files/attachments for labs."""
    __tablename__ = "lab_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    is_downloadable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    lab: Mapped[Lab] = relationship("Lab", back_populates="files")



# ============================================================================
# MODULE 4: DRILL MANAGEMENT
# ============================================================================

class Drill(Base):
    """Cyber drill exercise instances."""
    __tablename__ = "drills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    lab_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("labs.id", ondelete="SET NULL"))
    status: Mapped[DrillStatus] = mapped_column(Enum(DrillStatus, name='drill_status', values_callable=lambda x: [e.value for e in x]), nullable=False, default=DrillStatus.SCHEDULED)
    drill_type: Mapped[str] = mapped_column(String(50), nullable=False, default="individual")
    scheduled_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    max_participants: Mapped[Optional[int]] = mapped_column(Integer)
    rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    environment_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_drills_status", "status"),
        Index("idx_drills_lab", "lab_id"),
        Index("idx_drills_scheduled", "scheduled_start_at"),
    )


class DrillScenario(Base):
    """Link drills to labs with overrides."""
    __tablename__ = "drill_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    scenario_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("drill_id", "lab_id", name="uq_drill_scenarios"),
    )


class DrillParticipant(Base):
    """Track users participating in drills."""
    __tablename__ = "drill_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="participant")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("drill_id", "user_id", name="uq_drill_participants"),
    )


class DrillTeam(Base):
    """Teams participating in drills."""
    __tablename__ = "drill_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    team_side: Mapped[Optional[str]] = mapped_column(String(20))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("drill_id", "team_id", name="uq_drill_teams"),
    )


class DrillObjective(Base):
    """Objectives specific to drill instances."""
    __tablename__ = "drill_objectives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    lab_objective_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lab_objectives.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    side: Mapped[Optional[str]] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DrillAnnouncement(Base):
    """Announcements for drills."""
    __tablename__ = "drill_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    published_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================================
# MODULE 5: SUBMISSION SYSTEM
# ============================================================================

class Submission(Base):
    """Parent table for all submission types."""
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"))
    lab_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"))
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    submission_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[SubmissionStatus] = mapped_column(Enum(SubmissionStatus, name='submission_status', values_callable=lambda x: [e.value for e in x]), nullable=False, default=SubmissionStatus.PENDING)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    review_notes: Mapped[Optional[str]] = mapped_column(Text)


class FlagSubmission(Base):
    """Flag capture attempts."""
    __tablename__ = "flag_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    lab_flag_id: Mapped[int] = mapped_column(Integer, ForeignKey("lab_flags.id", ondelete="CASCADE"), nullable=False)
    flag_value: Mapped[str] = mapped_column(String(255), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    points_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time_decay_factor: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=1.00)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("submission_id", "lab_flag_id", name="uq_flag_submissions"),
    )


class EvidenceSubmission(Base):
    """Evidence file submissions."""
    __tablename__ = "evidence_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    objective_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lab_objectives.id", ondelete="SET NULL"))
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType, name='evidence_type', values_callable=lambda x: [e.value for e in x]), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReportSubmission(Base):
    """Report submissions."""
    __tablename__ = "report_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    quality_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    grade: Mapped[Optional[str]] = mapped_column(String(10))


class SubmissionAttempt(Base):
    """Track all flag submission attempts."""
    __tablename__ = "submission_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lab_flag_id: Mapped[int] = mapped_column(Integer, ForeignKey("lab_flags.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    flag_value: Mapped[str] = mapped_column(String(255), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(INET)

    __table_args__ = (
        UniqueConstraint("user_id", "lab_flag_id", "attempt_number", name="uq_submission_attempts"),
    )



# ============================================================================
# MODULE 6: SCORING SYSTEM
# ============================================================================

class Score(Base):
    """Current scores for users/teams in drills."""
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"))
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flags_captured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objectives_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hints_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    penalty_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time_bonus_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_blood_bonus: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    rank_position: Mapped[Optional[int]] = mapped_column(Integer)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "drill_id", name="uq_scores_user_drill"),
        UniqueConstraint("team_id", "drill_id", name="uq_scores_team_drill"),
    )


class ScoreHistory(Base):
    """Detailed score changes over time."""
    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"))
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    points_change: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_total: Mapped[int] = mapped_column(Integer, nullable=False)
    new_total: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FirstBlood(Base):
    """Track first capture of each flag per drill."""
    __tablename__ = "first_bloods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[int] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"), nullable=False)
    lab_flag_id: Mapped[int] = mapped_column(Integer, ForeignKey("lab_flags.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("drill_id", "lab_flag_id", name="uq_first_bloods"),
    )


# ============================================================================
# MODULE 7: BENCHMARKING SYSTEM
# ============================================================================

class Benchmark(Base):
    """Skill benchmark scores for users."""
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    offensive_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    defensive_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    web_exploitation_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    network_exploitation_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    active_directory_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    linux_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    windows_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    forensics_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    reporting_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    total_drills_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_flags_captured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_completion_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    last_calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BenchmarkHistory(Base):
    """Score progression over time."""
    __tablename__ = "benchmark_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="SET NULL"))
    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    offensive_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    defensive_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    web_exploitation_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    network_exploitation_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    active_directory_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    linux_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    windows_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    forensics_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    reporting_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================================
# MODULE 8: REPORTING SYSTEM
# ============================================================================

class Report(Base):
    """After-action reports and assessments."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"))
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, name='report_status', values_callable=lambda x: [e.value for e in x]), nullable=False, default=ReportStatus.DRAFT)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, default="after_action")
    quality_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    grade: Mapped[Optional[str]] = mapped_column(String(10))
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    graded_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    instructor_feedback: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ReportFinding(Base):
    """Individual findings within reports."""
    __tablename__ = "report_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(Integer, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[SeverityLevel] = mapped_column(Enum(SeverityLevel, name='severity_level', values_callable=lambda x: [e.value for e in x]), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    evidence: Mapped[Optional[str]] = mapped_column(Text)
    impact: Mapped[Optional[str]] = mapped_column(Text)
    recommendation: Mapped[Optional[str]] = mapped_column(Text)
    cvss_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 1))
    cwe_id: Mapped[Optional[str]] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Evidence(Base):
    """Evidence files for findings."""
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(Integer, ForeignKey("report_findings.id", ondelete="CASCADE"), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType, name='evidence_type', values_callable=lambda x: [e.value for e in x]), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================================
# MODULE 9: LEARNING PATH SYSTEM
# ============================================================================

class LearningPath(Base):
    """Structured learning path definitions."""
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[LabDifficulty] = mapped_column(Enum(LabDifficulty, name='lab_difficulty', values_callable=lambda x: [e.value for e in x]), nullable=False, default=LabDifficulty.BEGINNER)
    estimated_duration_hours: Mapped[Optional[int]] = mapped_column(Integer)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class LearningPathModule(Base):
    """Modules within learning paths."""
    __tablename__ = "learning_path_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    learning_path_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LearningPathLab(Base):
    """Labs required for modules."""
    __tablename__ = "learning_path_labs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_path_modules.id", ondelete="CASCADE"), nullable=False)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_score: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("module_id", "lab_id", name="uq_learning_path_labs"),
    )


class UserLearningProgress(Base):
    """Track user progress through learning paths."""
    __tablename__ = "user_learning_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    learning_path_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False)
    module_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_path_modules.id", ondelete="CASCADE"), nullable=False)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[LearningPathStatus] = mapped_column(Enum(LearningPathStatus, name='learning_path_status', values_callable=lambda x: [e.value for e in x]), nullable=False, default=LearningPathStatus.NOT_STARTED)
    score: Mapped[Optional[int]] = mapped_column(Integer)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "learning_path_id", "module_id", "lab_id", name="uq_user_learning_progress"),
    )


class LabSkill(Base):
    """Skills taught by each lab."""
    __tablename__ = "lab_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_id: Mapped[int] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_category: Mapped[str] = mapped_column(String(50), nullable=False)
    proficiency_level: Mapped[str] = mapped_column(String(20), nullable=False, default="intermediate")

    __table_args__ = (
        UniqueConstraint("lab_id", "skill_name", name="uq_lab_skills"),
    )


# ============================================================================
# MODULE 10: ADMIN & AUDIT SYSTEM
# ============================================================================

class AuditLog(Base):
    """Comprehensive audit trail for all system actions."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[AuditAction] = mapped_column(Enum(AuditAction, name='audit_action', values_callable=lambda x: [e.value for e in x]), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    actor_username: Mapped[Optional[str]] = mapped_column(String(100))
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[int]] = mapped_column(Integer)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SystemNotification(Base):
    """System-wide notifications."""
    __tablename__ = "system_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name='notification_type', values_callable=lambda x: [e.value for e in x]), nullable=False, default=NotificationType.INFO)
    target_audience: Mapped[str] = mapped_column(String(50), nullable=False, default="all")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserNotification(Base):
    """Track which notifications each user has read."""
    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_id: Mapped[int] = mapped_column(Integer, ForeignKey("system_notifications.id", ondelete="CASCADE"), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "notification_id", name="uq_user_notifications"),
    )


class PlatformSetting(Base):
    """System-wide configuration settings."""
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    setting_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LabEnvironmentLog(Base):
    """Lab environment event logs."""
    __tablename__ = "lab_environment_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drill_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("drills.id", ondelete="CASCADE"))
    lab_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("labs.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityEvent(Base):
    """Security incident tracking."""
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[SeverityLevel] = mapped_column(Enum(SeverityLevel, name='severity_level', values_callable=lambda x: [e.value for e in x]), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


