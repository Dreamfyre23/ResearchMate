"""Database configuration module for ResearchMate."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection and pooling settings."""

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/mas_database",
        validation_alias="DATABASE_URL",
        description="SQLAlchemy database connection URL",
    )
    echo_sql: bool = Field(
        default=False,
        validation_alias="DATABASE_ECHO",
        description="Whether to echo SQL statements",
    )
    pool_size: int = Field(
        default=5,
        validation_alias="DATABASE_POOL_SIZE",
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        validation_alias="DATABASE_MAX_OVERFLOW",
        description="Maximum connection pool overflow",
    )
    pool_timeout: int = Field(
        default=30,
        validation_alias="DATABASE_POOL_TIMEOUT",
        description="Connection pool timeout in seconds",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


def get_database_settings() -> DatabaseSettings:
    """Return an instance of DatabaseSettings loaded from the environment."""
    return DatabaseSettings()
