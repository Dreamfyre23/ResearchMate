"""Shared pytest configuration and fixtures for ResearchMate."""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from database.config import DatabaseSettings, get_database_settings
from database.connection import get_engine


@pytest.fixture(scope="session")
def db_settings() -> DatabaseSettings:
    """Provide database settings for tests."""
    return get_database_settings()


@pytest.fixture(scope="session")
def db_engine(db_settings: DatabaseSettings) -> Engine:
    """Provide a database engine for the test session."""
    return get_engine(settings=db_settings)


@pytest.fixture
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """Provide an isolated database session for a single test.

    Runs within a transaction that is rolled back at the end of the test,
    ensuring that no test data persists in the database.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
