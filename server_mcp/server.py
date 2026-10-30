"""Server-side MCP server for ResearchMate.

Implements an independently runnable MCP server over Streamable HTTP (DEC-005,
DEC-006, DEC-024) using the official Python MCP SDK.
"""

import logging
import sys
import time

import uvicorn
from mcp.server.mcpserver import MCPServer
from sqlalchemy.exc import SQLAlchemyError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from server_mcp.config import MCPServerSettings, get_server_settings
from server_mcp.resources.agent_information import register_agent_resources
from server_mcp.resources.notes_management import register_notes_resources
from server_mcp.resources.system_information import register_system_resources
from server_mcp.resources.task_management import register_task_resources
from server_mcp.tools.agent_information import register_agent_tools
from server_mcp.tools.file_management import register_file_tools
from server_mcp.tools.notes_management import register_notes_tools
from server_mcp.tools.task_management import register_task_tools

logger = logging.getLogger(__name__)

_SERVER_START_TIME: float = time.time()


def _check_db_status() -> str:
    """Safely check database connectivity without exposing connection strings."""
    try:
        from database.connection import check_connection

        return "connected" if check_connection() else "disconnected"
    except (SQLAlchemyError, OSError, ImportError) as exc:
        logger.debug("Database status check encountered error: %s", exc)
        return "unavailable"


def create_mcp_server(
    settings: MCPServerSettings | None = None,
    start_time: float | None = None,
) -> MCPServer:
    """Instantiate and configure the official MCPServer with diagnostic routes, tools, and resources."""
    active_settings = settings or get_server_settings()
    server_start_time = start_time if start_time is not None else _SERVER_START_TIME

    mcp_server = MCPServer(
        name=active_settings.server_name,
        version=active_settings.server_version,
        instructions="ResearchMate Model Context Protocol server exposing tool and resource ecosystem.",
    )

    # Register MCP resources and tools
    register_system_resources(mcp_server, server_start_time)
    register_agent_tools(mcp_server)
    register_agent_resources(mcp_server)
    register_task_tools(mcp_server)
    register_task_resources(mcp_server)
    register_notes_tools(mcp_server)
    register_notes_resources(mcp_server)
    register_file_tools(mcp_server, active_settings)

    # Register diagnostic HTTP routes outside the MCP protocol stream
    @mcp_server.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> JSONResponse:
        """Basic health check verifying server is responding."""
        return JSONResponse(
            {
                "status": "healthy",
                "server": active_settings.server_name,
                "version": active_settings.server_version,
            }
        )

    @mcp_server.custom_route("/status", methods=["GET"])
    async def status_check(_request: Request) -> JSONResponse:
        """Operational diagnostic status including database health."""
        db_status = _check_db_status()
        return JSONResponse(
            {
                "status": "operational",
                "service": active_settings.server_name,
                "version": active_settings.server_version,
                "transport": "streamable_http",
                "endpoint": active_settings.mcp_path,
                "database": db_status,
            }
        )

    return mcp_server


def create_app(
    settings: MCPServerSettings | None = None,
    server: MCPServer | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for Streamable HTTP."""
    active_settings = settings or get_server_settings()
    active_server = server or create_mcp_server(active_settings)
    return active_server.streamable_http_app(
        streamable_http_path=active_settings.mcp_path,
    )


def run_server(settings: MCPServerSettings | None = None) -> None:
    """Run the MCP server as an independent process."""
    active_settings = settings or get_server_settings()
    app = create_app(active_settings)
    logger.info(
        "Starting ResearchMate MCP Server on %s:%d (endpoint: %s)",
        active_settings.host,
        active_settings.port,
        active_settings.mcp_path,
    )
    uvicorn.run(
        app,
        host=active_settings.host,
        port=active_settings.port,
        log_level=active_settings.log_level.lower(),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    run_server()
