"""Configuration for the ResearchMate server-side MCP server."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerSettings(BaseSettings):
    """Server-side MCP configuration settings."""

    host: str = Field(
        default="127.0.0.1",
        validation_alias="MCP_SERVER_HOST",
        description="Host address to bind the MCP server",
    )
    port: int = Field(
        default=8000,
        validation_alias="MCP_SERVER_PORT",
        description="Port for the MCP server",
    )
    mcp_path: str = Field(
        default="/mcp",
        validation_alias="MCP_STREAMABLE_PATH",
        description="URL path for the Streamable HTTP endpoint",
    )
    server_name: str = Field(
        default="ResearchMate-MCP-Server",
        validation_alias="MCP_SERVER_NAME",
        description="Logical server name exposed during MCP handshake",
    )
    server_version: str = Field(
        default="0.1.0",
        validation_alias="MCP_SERVER_VERSION",
        description="Server version reported to MCP clients",
    )
    log_level: str = Field(
        default="info",
        validation_alias="MCP_LOG_LEVEL",
        description="Uvicorn and server logging level",
    )
    max_note_versions: int = Field(
        default=0,
        validation_alias="MAX_NOTE_VERSIONS",
        description="Maximum number of historical note versions to retain (0 = unlimited, DEC-031)",
    )
    workspace_root: str = Field(
        default="workspace",
        validation_alias="WORKSPACE_ROOT",
        description="Root directory for workspace files (DEC-032)",
    )
    max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024,
        validation_alias="MAX_FILE_SIZE_BYTES",
        description="Maximum file size in bytes permitted to read (default: 10MB)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


def get_server_settings() -> MCPServerSettings:
    """Return an instance of MCPServerSettings loaded from the environment."""
    return MCPServerSettings()
