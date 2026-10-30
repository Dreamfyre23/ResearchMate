"""Unit tests for SQLAlchemy models and UUID primary key defaults."""

import uuid

from database.models import (
    Agent,
    Base,
    Note,
    NotesTags,
    NoteTag,
    NoteVersion,
    Task,
    TaskDependency,
)


def test_model_table_names() -> None:
    """Verify that all ORM models define the expected table names."""
    assert Agent.__tablename__ == "agents"
    assert Task.__tablename__ == "tasks"
    assert TaskDependency.__tablename__ == "task_dependencies"
    assert Note.__tablename__ == "notes"
    assert NoteVersion.__tablename__ == "note_versions"
    assert NoteTag.__tablename__ == "note_tags"
    assert NotesTags.__tablename__ == "notes_tags"


def test_agent_model_instantiation() -> None:
    """Verify Agent instantiation and default attribute behavior."""
    agent = Agent(
        name="Research Agent",
        role="research",
        model="llama3.2:3b",
        provider="ollama",
    )
    assert agent.name == "Research Agent"
    assert agent.role == "research"
    assert agent.status == "active"
    assert agent.capabilities == []
    assert repr(agent).startswith("<Agent")


def test_task_model_instantiation() -> None:
    """Verify Task instantiation and soft delete defaults."""
    task = Task(
        title="Literature Review",
        description="Review papers on MCP architecture",
    )
    assert task.title == "Literature Review"
    assert task.status == "pending"
    assert task.priority == "medium"
    assert task.is_deleted is False
    assert task.deleted_at is None
    assert repr(task).startswith("<Task")


def test_task_dependency_instantiation() -> None:
    """Verify TaskDependency instantiation."""
    t1_id = uuid.uuid4()
    t2_id = uuid.uuid4()
    dep = TaskDependency(task_id=t1_id, depends_on_task_id=t2_id)
    assert dep.task_id == t1_id
    assert dep.depends_on_task_id == t2_id
    assert repr(dep).startswith("<TaskDependency")


def test_note_model_instantiation() -> None:
    """Verify Note instantiation and default fields."""
    note = Note(
        title="Key Findings",
        content="# Findings\n\n- Finding 1",
        category="technical_research",
    )
    assert note.title == "Key Findings"
    assert note.category == "technical_research"
    assert note.is_deleted is False
    assert note.deleted_at is None
    assert repr(note).startswith("<Note")


def test_note_version_instantiation() -> None:
    """Verify NoteVersion instantiation."""
    note_id = uuid.uuid4()
    version = NoteVersion(
        note_id=note_id,
        version_number=1,
        title="Initial Draft",
        content="Draft content",
        category="ideas",
    )
    assert version.note_id == note_id
    assert version.version_number == 1
    assert repr(version).startswith("<NoteVersion")


def test_note_tag_instantiation() -> None:
    """Verify NoteTag instantiation."""
    tag = NoteTag(name="Machine Learning")
    assert tag.name == "Machine Learning"
    assert repr(tag).startswith("<NoteTag")


def test_base_metadata_contains_all_tables() -> None:
    """Verify that Base.metadata registers all required tables."""
    expected_tables = {
        "agents",
        "tasks",
        "task_dependencies",
        "notes",
        "note_versions",
        "note_tags",
        "notes_tags",
    }
    registered = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(registered)
