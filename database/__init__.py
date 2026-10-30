"""Database package for ResearchMate.

Provides SQLAlchemy models, connection management, and migration tools.
"""

from database.config import DatabaseSettings, get_database_settings
from database.connection import (
    check_connection,
    ensure_database_exists,
    get_engine,
    get_session,
    get_session_factory,
)
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

__all__ = [
    "Agent",
    "Base",
    "DatabaseSettings",
    "Note",
    "NoteTag",
    "NoteVersion",
    "NotesTags",
    "Task",
    "TaskDependency",
    "check_connection",
    "ensure_database_exists",
    "get_database_settings",
    "get_engine",
    "get_session",
    "get_session_factory",
]
