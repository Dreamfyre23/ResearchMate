"""SQLAlchemy ORM models for ResearchMate.

Implements all entities, relationships, and constraints specified in
docs/DATABASE_DESIGN.md and accepted decisions (DEC-026, DEC-027, DEC-028,
DEC-029, DEC-030, DEC-031).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


# ---------------------------------------------------------------------------
# Entity 1: Agent
# ---------------------------------------------------------------------------
class Agent(Base):
    """Stores agents registered with ResearchMate."""

    __tablename__ = "agents"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique agent identifier (DEC-026).",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        doc="Agent unique display name.",
    )
    code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        unique=True,
        doc="Optional human-readable display code (e.g. AGENT-001).",
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Agent role (e.g. orchestrator, research, task_management).",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Description of agent purpose.",
    )
    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Model identifier used by the agent.",
    )
    provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Model provider (e.g. Google, Gemini).",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        doc="Application-reported runtime status.",
    )
    capabilities: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        doc="Capabilities and accessible MCP operations.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Record creation timestamp.",
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last activity timestamp reported by MAS.",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'busy', 'error')",
            name="ck_agents_status",
        ),
    )

    # Relationships
    assigned_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="assigned_agent",
        foreign_keys="[Task.assigned_agent_id]",
    )
    created_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="created_by_agent",
        foreign_keys="[Task.created_by_agent_id]",
    )
    created_notes: Mapped[list["Note"]] = relationship(
        "Note",
        back_populates="created_by_agent",
        foreign_keys="[Note.created_by_agent_id]",
    )
    changed_note_versions: Mapped[list["NoteVersion"]] = relationship(
        "NoteVersion",
        back_populates="changed_by_agent",
        foreign_keys="[NoteVersion.changed_by_agent_id]",
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "active")
        kwargs.setdefault("capabilities", [])
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<Agent(agent_id={self.agent_id}, name='{self.name}', role='{self.role}')>"
        )


# ---------------------------------------------------------------------------
# Entity 2: Task
# ---------------------------------------------------------------------------
class Task(Base):
    """Stores tasks managed by ResearchMate."""

    __tablename__ = "tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique task identifier (DEC-026).",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Short task title.",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed task description.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        doc="Task status: pending, in_progress, completed, cancelled.",
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
        doc="Task priority: low, medium, high, critical.",
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.agent_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Agent assigned to the task (DEC-027).",
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="Human user assigned to the task (reserved, DEC-027).",
    )
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.agent_id", ondelete="SET NULL"),
        nullable=True,
        doc="Agent creator attribution (DEC-027).",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="User creator attribution (reserved, DEC-027).",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
        index=True,
        doc="Soft-deletion flag (DEC-028).",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when task was soft-deleted (DEC-028).",
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Optional deadline for the task.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        doc="Record creation timestamp.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Most recent update timestamp.",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when task was marked completed.",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "NOT (assigned_agent_id IS NOT NULL AND assigned_user_id IS NOT NULL)",
            name="ck_tasks_assignment_mutual_exclusive",
        ),
        CheckConstraint(
            "NOT (created_by_agent_id IS NOT NULL AND created_by_user_id IS NOT NULL)",
            name="ck_tasks_creator_mutual_exclusive",
        ),
    )

    # Relationships
    assigned_agent: Mapped[Agent | None] = relationship(
        "Agent",
        back_populates="assigned_tasks",
        foreign_keys=[assigned_agent_id],
    )
    created_by_agent: Mapped[Agent | None] = relationship(
        "Agent",
        back_populates="created_tasks",
        foreign_keys=[created_by_agent_id],
    )
    dependencies: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        back_populates="task",
        foreign_keys="[TaskDependency.task_id]",
        cascade="all, delete-orphan",
    )
    dependents: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        back_populates="depends_on_task",
        foreign_keys="[TaskDependency.depends_on_task_id]",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "pending")
        kwargs.setdefault("priority", "medium")
        kwargs.setdefault("is_deleted", False)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Task(task_id={self.task_id}, title='{self.title[:30]}', status='{self.status}')>"


# ---------------------------------------------------------------------------
# Entity 3: TaskDependency
# ---------------------------------------------------------------------------
class TaskDependency(Base):
    """Stores dependency relationships between tasks."""

    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
        doc="Task that depends on another task.",
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        doc="Prerequisite task that must be completed first.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Timestamp when the dependency was recorded.",
    )

    __table_args__ = (
        CheckConstraint(
            "task_id != depends_on_task_id",
            name="ck_task_dependencies_no_self_dependency",
        ),
    )

    # Relationships
    task: Mapped[Task] = relationship(
        "Task",
        back_populates="dependencies",
        foreign_keys=[task_id],
    )
    depends_on_task: Mapped[Task] = relationship(
        "Task",
        back_populates="dependents",
        foreign_keys=[depends_on_task_id],
    )

    def __repr__(self) -> str:
        return f"<TaskDependency(task_id={self.task_id}, depends_on_task_id={self.depends_on_task_id})>"


# ---------------------------------------------------------------------------
# Entity 4: Note
# ---------------------------------------------------------------------------
class Note(Base):
    """Stores persistent notes and current content."""

    __tablename__ = "notes"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique note identifier (DEC-026).",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Short title describing the note.",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Current note content (Markdown format).",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Classification of the note.",
    )
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.agent_id", ondelete="SET NULL"),
        nullable=True,
        doc="Agent creator attribution (DEC-027).",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="User creator attribution (reserved, DEC-027).",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
        index=True,
        doc="Soft-deletion flag (DEC-029).",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when note was soft-deleted (DEC-029).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Record creation timestamp.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
        doc="Most recent update timestamp.",
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('technical_research', 'project_documentation', 'meeting_notes', 'ideas', 'general_knowledge', 'personal_notes')",
            name="ck_notes_category",
        ),
        CheckConstraint(
            "NOT (created_by_agent_id IS NOT NULL AND created_by_user_id IS NOT NULL)",
            name="ck_notes_creator_mutual_exclusive",
        ),
    )

    # Relationships
    created_by_agent: Mapped[Agent | None] = relationship(
        "Agent",
        back_populates="created_notes",
        foreign_keys=[created_by_agent_id],
    )
    versions: Mapped[list["NoteVersion"]] = relationship(
        "NoteVersion",
        back_populates="note",
        cascade="all, delete-orphan",
        order_by=lambda: desc(NoteVersion.version_number),
    )
    tags: Mapped[list["NoteTag"]] = relationship(
        "NoteTag",
        secondary="notes_tags",
        back_populates="notes",
        overlaps="note_tags_associations",
    )
    note_tags_associations: Mapped[list["NotesTags"]] = relationship(
        "NotesTags",
        back_populates="note",
        cascade="all, delete-orphan",
        overlaps="tags",
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("is_deleted", False)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Note(note_id={self.note_id}, title='{self.title[:30]}', category='{self.category}')>"


# ---------------------------------------------------------------------------
# Entity 5: NoteVersion
# ---------------------------------------------------------------------------
class NoteVersion(Base):
    """Stores historical versions of note content."""

    __tablename__ = "note_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique version identifier (DEC-026).",
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notes.note_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated note identifier.",
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Sequential version number for the note.",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Note title at this revision.",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Note body content at this revision.",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Note category at this revision.",
    )
    changed_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.agent_id", ondelete="SET NULL"),
        nullable=True,
        doc="Agent editor attribution (DEC-027).",
    )
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        doc="User editor attribution (reserved, DEC-027).",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Timestamp when this version snapshot was recorded.",
    )

    __table_args__ = (
        UniqueConstraint(
            "note_id", "version_number", name="uq_note_versions_note_id_version_number"
        ),
        CheckConstraint(
            "category IN ('technical_research', 'project_documentation', 'meeting_notes', 'ideas', 'general_knowledge', 'personal_notes')",
            name="ck_note_versions_category",
        ),
        CheckConstraint(
            "NOT (changed_by_agent_id IS NOT NULL AND changed_by_user_id IS NOT NULL)",
            name="ck_note_versions_changer_mutual_exclusive",
        ),
    )

    # Relationships
    note: Mapped[Note] = relationship(
        "Note",
        back_populates="versions",
    )
    changed_by_agent: Mapped[Agent | None] = relationship(
        "Agent",
        back_populates="changed_note_versions",
        foreign_keys=[changed_by_agent_id],
    )

    def __repr__(self) -> str:
        return f"<NoteVersion(version_id={self.version_id}, note_id={self.note_id}, v={self.version_number})>"


# ---------------------------------------------------------------------------
# Entity 6: NoteTag
# ---------------------------------------------------------------------------
class NoteTag(Base):
    """Stores normalized tags for categorizing notes."""

    __tablename__ = "note_tags"

    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique tag identifier (DEC-026).",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        doc="Unique tag name.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Tag creation timestamp.",
    )

    # Relationships
    notes: Mapped[list[Note]] = relationship(
        "Note",
        secondary="notes_tags",
        back_populates="tags",
        overlaps="note_tags_associations",
    )
    notes_tags_associations: Mapped[list["NotesTags"]] = relationship(
        "NotesTags",
        back_populates="tag",
        cascade="all, delete-orphan",
        overlaps="notes,tags",
    )

    def __repr__(self) -> str:
        return f"<NoteTag(tag_id={self.tag_id}, name='{self.name}')>"


# ---------------------------------------------------------------------------
# Entity 7: NotesTags
# ---------------------------------------------------------------------------
class NotesTags(Base):
    """Association table linking notes and tags (many-to-many)."""

    __tablename__ = "notes_tags"

    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notes.note_id", ondelete="CASCADE"),
        primary_key=True,
        doc="Associated note identifier.",
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("note_tags.tag_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
        doc="Associated tag identifier.",
    )

    # Relationships
    note: Mapped[Note] = relationship(
        "Note",
        back_populates="note_tags_associations",
        overlaps="notes,tags",
    )
    tag: Mapped[NoteTag] = relationship(
        "NoteTag",
        back_populates="notes_tags_associations",
        overlaps="notes,tags",
    )

    def __repr__(self) -> str:
        return f"<NotesTags(note_id={self.note_id}, tag_id={self.tag_id})>"
