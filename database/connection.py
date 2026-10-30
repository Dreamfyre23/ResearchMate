"""PostgreSQL connection and session management for ResearchMate."""

import logging
import urllib.parse
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from database.config import DatabaseSettings, get_database_settings

logger = logging.getLogger(__name__)

# Module-level singletons (lazily initialized)
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def ensure_database_exists(database_url: str | None = None) -> bool:
    """Ensure the target PostgreSQL database exists.

    Connects to the default 'postgres' database on the same host to verify
    the target database exists, creating it if necessary. Never drops or resets
    an existing database.

    Returns:
        True if the database already existed or was successfully created.
    """
    settings = get_database_settings()
    url = database_url or settings.database_url

    # Normalize url for psycopg
    clean_url = url.replace("postgresql+psycopg://", "postgresql://")
    parsed = urllib.parse.urlparse(clean_url)
    target_db = parsed.path.lstrip("/")
    if not target_db:
        raise ValueError("Database name is missing from the database URL.")

    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    user = parsed.username or "postgres"
    password = parsed.password

    try:
        with (
            psycopg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname="postgres",
                autocommit=True,
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s;",
                (target_db,),
            )
            if cur.fetchone():
                logger.debug("Database '%s' already exists.", target_db)
                return True

            logger.info("Database '%s' does not exist. Creating...", target_db)
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            logger.info("Database '%s' created successfully.", target_db)
            return True
    except Exception as exc:
        logger.error("Failed to verify or create database '%s': %s", target_db, exc)
        raise


def get_engine(
    database_url: str | None = None,
    echo: bool | None = None,
    settings: DatabaseSettings | None = None,
) -> Engine:
    """Create or return the global SQLAlchemy Engine instance."""
    global _engine
    if database_url is not None or echo is not None:
        # Caller requested specific settings, return a dedicated engine
        active_settings = settings or get_database_settings()
        url = database_url or active_settings.database_url
        echo_sql = echo if echo is not None else active_settings.echo_sql
        return create_engine(
            url,
            echo=echo_sql,
            pool_size=active_settings.pool_size,
            max_overflow=active_settings.max_overflow,
            pool_timeout=active_settings.pool_timeout,
        )

    if _engine is None:
        active_settings = settings or get_database_settings()
        _engine = create_engine(
            active_settings.database_url,
            echo=active_settings.echo_sql,
            pool_size=active_settings.pool_size,
            max_overflow=active_settings.max_overflow,
            pool_timeout=active_settings.pool_timeout,
        )
    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Create or return the sessionmaker factory."""
    global _session_factory
    if engine is not None:
        return sessionmaker(autocommit=False, autoflush=False, bind=engine)

    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _session_factory


@contextmanager
def get_session(
    session_factory: sessionmaker[Session] | None = None,
) -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback.

    Yields:
        SQLAlchemy Session object.
    """
    factory = session_factory or get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection(engine: Engine | None = None) -> bool:
    """Verify connectivity to PostgreSQL.

    Returns:
        True if the database responds to a simple query, False otherwise.
    """
    eng = engine or get_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, OSError) as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return False
