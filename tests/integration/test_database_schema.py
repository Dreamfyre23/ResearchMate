"""Integration tests verifying database schema against DATABASE_DESIGN.md."""

from sqlalchemy import Engine, inspect


def test_schema_tables_exist(db_engine: Engine) -> None:
    """Verify all 7 required application tables exist in mas_database."""
    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())
    required_tables = {
        "agents",
        "tasks",
        "task_dependencies",
        "notes",
        "note_versions",
        "note_tags",
        "notes_tags",
    }
    assert required_tables.issubset(existing_tables)


def test_agents_table_schema(db_engine: Engine) -> None:
    """Verify agents table columns and primary key."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("agents")}

    assert "agent_id" in columns
    assert "name" in columns
    assert "code" in columns
    assert "role" in columns
    assert "status" in columns
    assert "capabilities" in columns
    assert "created_at" in columns
    assert "last_active_at" in columns

    pk = inspector.get_pk_constraint("agents")
    assert pk["constrained_columns"] == ["agent_id"]


def test_tasks_table_schema(db_engine: Engine) -> None:
    """Verify tasks table columns, soft-delete fields, and primary key."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("tasks")}

    assert "task_id" in columns
    assert "title" in columns
    assert "status" in columns
    assert "priority" in columns
    assert "assigned_agent_id" in columns
    assert "assigned_user_id" in columns
    assert "created_by_agent_id" in columns
    assert "created_by_user_id" in columns
    assert "is_deleted" in columns
    assert "deleted_at" in columns
    assert "due_date" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    pk = inspector.get_pk_constraint("tasks")
    assert pk["constrained_columns"] == ["task_id"]


def test_task_dependencies_table_schema(db_engine: Engine) -> None:
    """Verify composite primary key on task_dependencies."""
    inspector = inspect(db_engine)
    pk = inspector.get_pk_constraint("task_dependencies")
    assert set(pk["constrained_columns"]) == {"task_id", "depends_on_task_id"}


def test_notes_table_schema(db_engine: Engine) -> None:
    """Verify notes table columns, soft-delete fields, and primary key."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("notes")}

    assert "note_id" in columns
    assert "title" in columns
    assert "content" in columns
    assert "category" in columns
    assert "is_deleted" in columns
    assert "deleted_at" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    pk = inspector.get_pk_constraint("notes")
    assert pk["constrained_columns"] == ["note_id"]


def test_note_versions_table_schema(db_engine: Engine) -> None:
    """Verify note_versions table columns and primary key."""
    inspector = inspect(db_engine)
    columns = {c["name"]: c for c in inspector.get_columns("note_versions")}

    assert "version_id" in columns
    assert "note_id" in columns
    assert "version_number" in columns
    assert "title" in columns
    assert "content" in columns
    assert "category" in columns

    pk = inspector.get_pk_constraint("note_versions")
    assert pk["constrained_columns"] == ["version_id"]


def test_notes_tags_table_schema(db_engine: Engine) -> None:
    """Verify composite primary key on notes_tags association table."""
    inspector = inspect(db_engine)
    pk = inspector.get_pk_constraint("notes_tags")
    assert set(pk["constrained_columns"]) == {"note_id", "tag_id"}
