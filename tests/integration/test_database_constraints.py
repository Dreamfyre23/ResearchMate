"""Integration tests for PostgreSQL constraints across models."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import (
    Agent,
    Note,
    NoteTag,
    NoteVersion,
    Task,
    TaskDependency,
)


def test_agent_status_constraint(db_session: Session) -> None:
    """Verify that invalid agent status is rejected by check constraint."""
    agent = Agent(
        name="Invalid Status Agent",
        role="research",
        status="unsupported_status",
    )
    db_session.add(agent)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_agent_name_unique_constraint(db_session: Session) -> None:
    """Verify that duplicate agent names are rejected."""
    a1 = Agent(name="Unique Agent", role="research")
    a2 = Agent(name="Unique Agent", role="task_management")
    db_session.add(a1)
    db_session.flush()
    db_session.add(a2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_status_constraint(db_session: Session) -> None:
    """Verify that invalid task status is rejected by check constraint."""
    task = Task(title="Test Task", status="invalid_status")
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_priority_constraint(db_session: Session) -> None:
    """Verify that invalid task priority is rejected by check constraint."""
    task = Task(title="Test Task", priority="super_urgent")
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_assignment_mutual_exclusivity(db_session: Session) -> None:
    """Verify that a task cannot have both agent and user assigned (DEC-027)."""
    agent = Agent(name="Assignment Agent", role="task_management")
    db_session.add(agent)
    db_session.flush()

    task = Task(
        title="Double Assigned Task",
        assigned_agent_id=agent.agent_id,
        assigned_user_id=uuid.uuid4(),
    )
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_creator_mutual_exclusivity(db_session: Session) -> None:
    """Verify that a task cannot have both agent and user creator (DEC-027)."""
    agent = Agent(name="Creator Agent", role="research")
    db_session.add(agent)
    db_session.flush()

    task = Task(
        title="Double Created Task",
        created_by_agent_id=agent.agent_id,
        created_by_user_id=uuid.uuid4(),
    )
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_task_dependency_no_self_dependency(db_session: Session) -> None:
    """Verify that a task cannot depend on itself."""
    task = Task(title="Self Dependent Task")
    db_session.add(task)
    db_session.flush()

    dep = TaskDependency(task_id=task.task_id, depends_on_task_id=task.task_id)
    db_session.add(dep)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_note_category_constraint(db_session: Session) -> None:
    """Verify that invalid note category is rejected by check constraint."""
    note = Note(
        title="Invalid Category Note",
        content="Content",
        category="nonexistent_category",
    )
    db_session.add(note)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_note_version_unique_constraint(db_session: Session) -> None:
    """Verify duplicate version numbers for the same note are rejected."""
    note = Note(
        title="Versioned Note",
        content="V1 Content",
        category="technical_research",
    )
    db_session.add(note)
    db_session.flush()

    v1 = NoteVersion(
        note_id=note.note_id,
        version_number=1,
        title="Title V1",
        content="Content V1",
        category="technical_research",
    )
    v2 = NoteVersion(
        note_id=note.note_id,
        version_number=1,
        title="Title V1 Duplicate",
        content="Content V1 Dup",
        category="technical_research",
    )
    db_session.add(v1)
    db_session.flush()
    db_session.add(v2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_note_tag_unique_constraint(db_session: Session) -> None:
    """Verify that duplicate tag names are rejected."""
    t1 = NoteTag(name="ai-agents")
    t2 = NoteTag(name="ai-agents")
    db_session.add(t1)
    db_session.flush()
    db_session.add(t2)
    with pytest.raises(IntegrityError):
        db_session.flush()
