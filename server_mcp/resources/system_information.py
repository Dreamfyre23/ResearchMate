"""System Information MCP resources for ResearchMate.

Implements the five read-only resources specified in docs/MCP/System Information.md:
- system://status
- system://statistics
- system://available-tools
- system://server-info
- system://database-info
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from database.connection import get_session
from database.models import Agent, Note, Task
from server_mcp.config import MCPServerSettings, get_server_settings

logger = logging.getLogger(__name__)


def get_database_info() -> dict[str, Any]:
    """Retrieve non-sensitive database connection and version info."""
    try:
        with get_session() as session:
            version_row = session.execute(text("SELECT version()")).scalar()
            return {
                "status": "connected",
                "database_type": "PostgreSQL",
                "database_version": str(version_row) if version_row else "Unknown",
            }
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Database info check failed: %s", exc)
        return {
            "status": "disconnected",
            "database_type": "PostgreSQL",
            "database_version": None,
        }


def get_system_status(start_time: float, settings: MCPServerSettings) -> dict[str, Any]:
    """Compile operational status of server and database."""
    uptime = round(time.time() - start_time, 2)
    db_info = get_database_info()
    overall_status = "running" if db_info["status"] == "connected" else "degraded"

    return {
        "server_name": settings.server_name,
        "status": overall_status,
        "version": settings.server_version,
        "uptime_seconds": uptime,
        "database": db_info,
    }


def get_system_statistics(workspace_dir: str = "workspace") -> dict[str, Any]:
    """Aggregate live counts from PostgreSQL and workspace filesystem."""
    stats: dict[str, Any] = {
        "tasks": {
            "total": 0,
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "cancelled": 0,
        },
        "notes": {
            "total": 0,
        },
        "files": {
            "total": 0,
        },
        "agents": {
            "registered": 0,
            "active": 0,
            "inactive": 0,
            "busy": 0,
            "error": 0,
        },
    }

    # Count database entities (excluding soft-deleted tasks/notes per DEC-028, DEC-029)
    try:
        with get_session() as session:
            # Tasks breakdown
            tasks_query = (
                select(Task.status, func.count(Task.task_id))
                .where(Task.is_deleted.is_(False))
                .group_by(Task.status)
            )
            for task_status, count in session.execute(tasks_query):
                if task_status in stats["tasks"]:
                    stats["tasks"][task_status] = count
            stats["tasks"]["total"] = sum(
                stats["tasks"][k]
                for k in ("pending", "in_progress", "completed", "cancelled")
            )

            # Notes total
            notes_count = session.scalar(
                select(func.count(Note.note_id)).where(Note.is_deleted.is_(False))
            )
            stats["notes"]["total"] = notes_count or 0

            # Agents breakdown
            agents_query = select(Agent.status, func.count(Agent.agent_id)).group_by(
                Agent.status
            )
            total_agents = 0
            for agent_status, count in session.execute(agents_query):
                total_agents += count
                if agent_status in stats["agents"]:
                    stats["agents"][agent_status] = count
            stats["agents"]["registered"] = total_agents

    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Could not calculate database statistics: %s", exc)
        stats["database_error"] = "Database unavailable for statistics query"

    # Count workspace files
    try:
        ws_path = Path(workspace_dir)
        if ws_path.is_dir():
            file_count = sum(
                1
                for p in ws_path.rglob("*")
                if p.is_file() and not p.name.startswith(".")
            )
            stats["files"]["total"] = file_count
    except OSError as exc:
        logger.warning("Could not count workspace files: %s", exc)

    return stats


def get_available_tools(server: MCPServer) -> dict[str, Any]:
    """Group currently registered tools by category for inspection."""
    # Group tools by known category mapping
    agent_info_tools = {"get_agent_info", "list_agents", "get_agent_tasks"}
    task_mgmt_tools = {
        "create_task",
        "get_task",
        "get_tasks",
        "update_task",
        "delete_task",
        "search_tasks",
    }
    notes_mgmt_tools = {
        "create_note",
        "get_note",
        "get_notes",
        "update_note",
        "delete_note",
        "search_notes",
    }
    file_mgmt_tools = {"list_files", "read_file", "search_files", "get_file_metadata"}

    # Extract all currently registered tool names from the MCPServer
    registered_names: set[str] = set()
    if hasattr(server, "_tool_manager") and hasattr(server._tool_manager, "_tools"):
        registered_names = set(server._tool_manager._tools.keys())
    elif hasattr(server, "_tools"):
        registered_names = set(server._tools.keys())

    categories = []

    active_agent_tools = sorted(registered_names & agent_info_tools)
    if active_agent_tools:
        categories.append({"name": "Agent Information", "tools": active_agent_tools})

    active_task_tools = sorted(registered_names & task_mgmt_tools)
    if active_task_tools:
        categories.append({"name": "Task Management", "tools": active_task_tools})

    active_notes_tools = sorted(registered_names & notes_mgmt_tools)
    if active_notes_tools:
        categories.append({"name": "Notes Management", "tools": active_notes_tools})

    active_file_tools = sorted(registered_names & file_mgmt_tools)
    if active_file_tools:
        categories.append({"name": "File Management", "tools": active_file_tools})

    # Catch any additional tools not in standard categories
    known_tools = (
        agent_info_tools | task_mgmt_tools | notes_mgmt_tools | file_mgmt_tools
    )
    other_tools = sorted(registered_names - known_tools)
    if other_tools:
        categories.append({"name": "Other Tools", "tools": other_tools})

    total_tools = sum(len(c["tools"]) for c in categories)
    return {
        "total_tools": total_tools,
        "categories": categories,
    }


def get_server_info(settings: MCPServerSettings) -> dict[str, Any]:
    """Provide non-sensitive server version and capabilities."""
    return {
        "server_name": settings.server_name,
        "version": settings.server_version,
        "server_version": settings.server_version,
        "protocol_transport": "Streamable HTTP",
        "transport": "streamable_http",
        "supported_capabilities": ["tools", "resources"],
    }


def register_system_resources(server: MCPServer, start_time: float) -> None:
    """Register all 5 System Information MCP resources."""
    settings = get_server_settings()

    @server.resource(
        "system://status",
        name="System Status",
        description="Provides operational status of the MCP server and its database dependency.",
        mime_type="application/json",
    )
    async def status_resource() -> str:
        return json.dumps(get_system_status(start_time, settings), indent=2)

    @server.resource(
        "system://statistics",
        name="System Statistics",
        description="Provides aggregated statistics about tasks, notes, files, and agents.",
        mime_type="application/json",
    )
    async def statistics_resource() -> str:
        return json.dumps(get_system_statistics(), indent=2)

    @server.resource(
        "system://available-tools",
        name="Available Tools",
        description="Provides a categorized overview of registered MCP tools.",
        mime_type="application/json",
    )
    async def available_tools_resource() -> str:
        return json.dumps(get_available_tools(server), indent=2)

    @server.resource(
        "system://server-info",
        name="Server Information",
        description="Provides non-sensitive server version and supported MCP capabilities.",
        mime_type="application/json",
    )
    async def server_info_resource() -> str:
        return json.dumps(get_server_info(settings), indent=2)

    @server.resource(
        "system://database-info",
        name="Database Information",
        description="Provides non-sensitive database connection status and version details.",
        mime_type="application/json",
    )
    async def database_info_resource() -> str:
        return json.dumps(get_database_info(), indent=2)
