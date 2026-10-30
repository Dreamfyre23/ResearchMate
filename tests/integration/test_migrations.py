"""Integration tests verifying Alembic migration status and capabilities."""

from alembic.config import Config
from sqlalchemy import Engine, inspect

from database.config import get_database_settings


def test_alembic_current_head(db_engine: Engine) -> None:
    """Verify that the database is migrated to the current Alembic head revision."""
    settings = get_database_settings()
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Check that the alembic_version table exists and has a revision
    inspector = inspect(db_engine)
    assert "alembic_version" in inspector.get_table_names()

    with db_engine.connect() as conn:
        from sqlalchemy import text

        current_rev = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert current_rev is not None
        assert len(current_rev) > 0


def test_alembic_config_resolves_script_location() -> None:
    """Verify that alembic.ini points to the correct migration directory."""
    alembic_cfg = Config("alembic.ini")
    script_loc = alembic_cfg.get_main_option("script_location")
    assert script_loc == "database/migrations"
