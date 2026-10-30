"""Integration tests for foreign-key relationships, cascading, and soft deletion."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    Agent,
    Note,
    NoteTag,
    NoteVersion,
    Task,
    TaskDependency,
)


def test_agent_task_relationships(db_session: Session) -> None:
    """Verify task assignment and creation relationships with Agent."""
    agent = Agent(name="Task Worker Agent", role="task_management")
    db_session.add(agent)
    db_session.flush()

    task = Task(
        title="Implementation Task",
        assigned_agent=agent,
        created_by_agent=agent,
    )
    db_session.add(task)
    db_session.flush()

    assert task.assigned_agent_id == agent.agent_id
    assert task.created_by_agent_id == agent.agent_id
    assert task in agent.assigned_tasks
    assert task in agent.created_tasks


def test_task_dependencies_relationship(db_session: Session) -> None:
    """Verify task dependencies and dependents relationships."""
    prerequisite = Task(title="Design Phase")
    dependent = Task(title="Build Phase")
    db_session.add_all([prerequisite, dependent])
    db_session.flush()

    dep = TaskDependency(
        task_id=dependent.task_id,
        depends_on_task_id=prerequisite.task_id,
    )
    db_session.add(dep)
    db_session.flush()

    assert len(dependent.dependencies) == 1
    assert dependent.dependencies[0].depends_on_task_id == prerequisite.task_id
    assert len(prerequisite.dependents) == 1
    assert prerequisite.dependents[0].task_id == dependent.task_id


def test_note_version_relationship(db_session: Session) -> None:
    """Verify note to note_versions relationship and ordering."""
    note = Note(
        title="Living Document",
        content="Version 3 active content",
        category="project_documentation",
    )
    db_session.add(note)
    db_session.flush()

    v1 = NoteVersion(
        note_id=note.note_id,
        version_number=1,
        title="Living Document V1",
        content="Version 1 content",
        category="project_documentation",
    )
    v2 = NoteVersion(
        note_id=note.note_id,
        version_number=2,
        title="Living Document V2",
        content="Version 2 content",
        category="project_documentation",
    )
    db_session.add_all([v1, v2])
    db_session.flush()

    # Note versions are ordered by version_number desc
    assert len(note.versions) == 2
    assert note.versions[0].version_number == 2
    assert note.versions[1].version_number == 1


def test_note_tags_many_to_many(db_session: Session) -> None:
    """Verify note and tag many-to-many relationship."""
    note = Note(
        title="Tagged Note",
        content="Notes with multiple tags",
        category="general_knowledge",
    )
    tag1 = NoteTag(name="python")
    tag2 = NoteTag(name="database")
    note.tags.extend([tag1, tag2])
    db_session.add(note)
    db_session.flush()

    assert len(note.tags) == 2
    assert note in tag1.notes
    assert note in tag2.notes


def test_task_soft_delete_query_filtering(db_session: Session) -> None:
    """Verify soft-deleted tasks are identifiable and filterable (DEC-028)."""
    t_active = Task(title="Active Task", is_deleted=False)
    t_deleted = Task(
        title="Deleted Task",
        is_deleted=True,
        deleted_at=datetime.now(UTC),
    )
    db_session.add_all([t_active, t_deleted])
    db_session.flush()

    active_tasks = db_session.scalars(
        select(Task).where(Task.is_deleted.is_(False)),
    ).all()
    active_titles = [t.title for t in active_tasks]
    assert "Active Task" in active_titles
    assert "Deleted Task" not in active_titles


def test_note_soft_delete_query_filtering(db_session: Session) -> None:
    """Verify soft-deleted notes are identifiable and filterable (DEC-029)."""
    n_active = Note(
        title="Active Note",
        content="Active",
        category="ideas",
        is_deleted=False,
    )
    n_deleted = Note(
        title="Deleted Note",
        content="Deleted",
        category="ideas",
        is_deleted=True,
        deleted_at=datetime.now(UTC),
    )
    db_session.add_all([n_active, n_deleted])
    db_session.flush()

    active_notes = db_session.scalars(
        select(Note).where(Note.is_deleted.is_(False)),
    ).all()
    active_titles = [n.title for n in active_notes]
    assert "Active Note" in active_titles
    assert "Deleted Note" not in active_titles
