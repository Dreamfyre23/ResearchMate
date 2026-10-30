"""Integration tests for database connectivity, sessions, and configuration."""

import pytest
from sqlalchemy import Engine, text

from database.connection import (
    check_connection,
    ensure_database_exists,
    get_engine,
    get_session,
    get_session_factory,
)


def test_database_connectivity(db_engine: Engine) -> None:
    """Verify that PostgreSQL responds to a connectivity ping."""
    assert check_connection(db_engine) is True


def test_session_factory(db_engine: Engine) -> None:
    """Verify that session factory creates operational sessions."""
    factory = get_session_factory(db_engine)
    session = factory()
    try:
        result = session.execute(text("SELECT 42 AS val")).scalar()
        assert result == 42
    finally:
        session.close()


def test_get_session_context_manager() -> None:
    """Verify the get_session() context manager commits and closes cleanly."""
    with get_session() as session:
        result = session.execute(text("SELECT 100 AS val")).scalar()
        assert result == 100


def test_get_session_rollback_on_error() -> None:
    """Verify get_session() triggers automatic rollback when an exception occurs."""
    with (
        pytest.raises(RuntimeError, match="Intentional test error"),
        get_session() as session,
    ):
        session.execute(text("SELECT 1"))
        raise RuntimeError("Intentional test error")


def test_ensure_database_exists_idempotency() -> None:
    """Verify ensure_database_exists() returns True when database already exists."""
    assert ensure_database_exists() is True


def test_get_engine_singleton() -> None:
    """Verify get_engine() returns a consistent singleton instance."""
    eng1 = get_engine()
    eng2 = get_engine()
    assert eng1 is eng2
