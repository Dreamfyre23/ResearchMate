"""Configuration for the ResearchMate client-side MCP host.

Provides settings management for connecting to the server-side MCP endpoint over
Streamable HTTP (DEC-005, DEC-006, DEC-024).
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPClientSettings(BaseSettings):
    """Client-side MCP configuration settings."""

    server_url: str = Field(
        default="http://127.0.0.1:8000/mcp",
        validation_alias="MCP_SERVER_URL",
        description="Streamable HTTP endpoint URL for the MCP server",
    )
    timeout_seconds: float = Field(
        default=30.0,
        validation_alias="MCP_CLIENT_TIMEOUT_SECONDS",
        description="Timeout in seconds for MCP client network requests",
    )
    max_retries: int = Field(
        default=3,
        validation_alias="MCP_CLIENT_MAX_RETRIES",
        description="Maximum retry attempts on transient network connection errors",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        validation_alias="MCP_CLIENT_RETRY_DELAY_SECONDS",
        description="Delay between retry attempts in seconds",
    )
    log_level: str = Field(
        default="info",
        validation_alias="MCP_CLIENT_LOG_LEVEL",
        description="Logging level for client-side MCP host",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


def get_client_settings() -> MCPClientSettings:
    """Return an instance of MCPClientSettings loaded from the environment."""
    return MCPClientSettings()
