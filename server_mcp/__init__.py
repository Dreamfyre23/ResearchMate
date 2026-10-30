"""Server-side Model Context Protocol (MCP) package for ResearchMate."""

from server_mcp.config import MCPServerSettings, get_server_settings
from server_mcp.resources.agent_information import register_agent_resources
from server_mcp.resources.notes_management import register_notes_resources
from server_mcp.resources.system_information import register_system_resources
from server_mcp.resources.task_management import register_task_resources
from server_mcp.server import create_app, create_mcp_server, run_server
from server_mcp.tools.agent_information import register_agent_tools
from server_mcp.tools.file_management import (
    ensure_workspace_directories,
    get_workspace_root,
    register_file_tools,
)
from server_mcp.tools.notes_management import register_notes_tools
from server_mcp.tools.task_management import register_task_tools

__all__ = [
    "MCPServerSettings",
    "create_app",
    "create_mcp_server",
    "ensure_workspace_directories",
    "get_server_settings",
    "get_workspace_root",
    "register_agent_resources",
    "register_agent_tools",
    "register_file_tools",
    "register_notes_resources",
    "register_notes_tools",
    "register_system_resources",
    "register_task_resources",
    "register_task_tools",
    "run_server",
]
