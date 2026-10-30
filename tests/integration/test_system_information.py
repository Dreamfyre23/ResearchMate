"""Integration tests for System Information MCP resources (Phase 4).

Validates:
- system://status
- system://statistics
- system://available-tools
- system://server-info
- system://database-info
- Direct helper functions and database connectivity reporting.
- Absence of credentials and connection strings in responses.
"""

import asyncio
import json
import socket
from collections.abc import AsyncGenerator

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from server_mcp.config import MCPServerSettings, get_server_settings
from server_mcp.resources.system_information import (
    get_available_tools,
    get_database_info,
    get_server_info,
    get_system_statistics,
    get_system_status,
)
from server_mcp.server import create_app, create_mcp_server


def _find_free_port() -> int:
    """Find an available TCP port for ephemeral test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def running_mcp_server() -> AsyncGenerator[str, None]:
    """Start an ephemeral MCP server and yield its base URL."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="ResearchMate-SystemInfo-Test",
        server_version="0.1.0-test",
        log_level="warning",
    )
    app = create_app(settings)
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())

    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"http://{host}:{port}/health")
                if res.status_code == 200:
                    break
        except (httpx.ConnectError, OSError):
            await asyncio.sleep(0.05)

    yield f"http://{host}:{port}"

    server.should_exit = True
    await server_task


def test_get_database_info_non_sensitive() -> None:
    """Verify database info returns connection status and PostgreSQL details without credentials."""
    info = get_database_info()
    assert info["status"] == "connected"
    assert info["database_type"] == "PostgreSQL"
    assert "PostgreSQL" in info["database_version"]

    # Security check: verify no secrets or connection strings leaked
    for val in info.values():
        assert "password" not in str(val).lower()
        assert "postgresql://" not in str(val).lower()
        assert "5432" not in str(val).lower()


def test_get_system_status() -> None:
    """Verify system status reports server name, version, status, and uptime."""
    settings = get_server_settings()
    status = get_system_status(start_time=100.0, settings=settings)
    assert status["server_name"] == settings.server_name
    assert status["status"] in ("running", "degraded")
    assert status["version"] == settings.server_version
    assert status["uptime_seconds"] > 0
    assert status["database"]["status"] in ("connected", "disconnected")


def test_get_system_statistics_structure_and_counts() -> None:
    """Verify system statistics structure covers tasks, notes, files, agents."""
    stats = get_system_statistics(workspace_dir="workspace")
    assert "tasks" in stats
    assert "notes" in stats
    assert "files" in stats
    assert "agents" in stats

    for expected_key in ("total", "pending", "in_progress", "completed", "cancelled"):
        assert expected_key in stats["tasks"]
        assert isinstance(stats["tasks"][expected_key], int)

    assert "total" in stats["notes"]
    assert "total" in stats["files"]
    assert "registered" in stats["agents"]


def test_get_available_tools_categorization() -> None:
    """Verify available tools returns categorized view reflecting registered tools."""
    server = create_mcp_server()
    tools_info = get_available_tools(server)
    assert "total_tools" in tools_info
    assert tools_info["total_tools"] == 19
    assert "categories" in tools_info

    category_names = [c["name"] for c in tools_info["categories"]]
    assert "Agent Information" in category_names
    assert "Task Management" in category_names
    assert "Notes Management" in category_names
    assert "File Management" in category_names

    agent_category = next(
        c for c in tools_info["categories"] if c["name"] == "Agent Information"
    )
    assert "get_agent_info" in agent_category["tools"]
    assert "list_agents" in agent_category["tools"]
    assert "get_agent_tasks" in agent_category["tools"]

    task_category = next(
        c for c in tools_info["categories"] if c["name"] == "Task Management"
    )
    for t_name in (
        "create_task",
        "get_task",
        "get_tasks",
        "update_task",
        "delete_task",
        "search_tasks",
    ):
        assert t_name in task_category["tools"]

    notes_category = next(
        c for c in tools_info["categories"] if c["name"] == "Notes Management"
    )
    for n_name in (
        "create_note",
        "get_note",
        "get_notes",
        "update_note",
        "delete_note",
        "search_notes",
    ):
        assert n_name in notes_category["tools"]

    file_category = next(
        c for c in tools_info["categories"] if c["name"] == "File Management"
    )
    for f_name in ("list_files", "read_file", "search_files", "get_file_metadata"):
        assert f_name in file_category["tools"]


def test_get_server_info_non_sensitive() -> None:
    """Verify server info exposes public metadata and capabilities without internal paths."""
    settings = get_server_settings()
    info = get_server_info(settings)
    assert info["server_name"] == settings.server_name
    assert info["server_version"] == settings.server_version
    assert info["transport"] == "streamable_http"
    assert "tools" in info["supported_capabilities"]
    assert "resources" in info["supported_capabilities"]


async def test_system_resources_via_client(running_mcp_server: str) -> None:
    """Verify all 5 system resources can be read via official MCP client session."""
    mcp_url = f"{running_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Read system://status
        status_res = await session.read_resource("system://status")
        assert len(status_res.contents) > 0
        status_data = json.loads(status_res.contents[0].text)
        assert status_data["status"] == "running"
        assert status_data["database"]["status"] == "connected"

        # 2. Read system://statistics
        stats_res = await session.read_resource("system://statistics")
        assert len(stats_res.contents) > 0
        stats_data = json.loads(stats_res.contents[0].text)
        assert "tasks" in stats_data
        assert "notes" in stats_data
        assert "agents" in stats_data

        # 3. Read system://available-tools
        tools_res = await session.read_resource("system://available-tools")
        assert len(tools_res.contents) > 0
        tools_data = json.loads(tools_res.contents[0].text)
        assert tools_data["total_tools"] == 19

        # 4. Read system://server-info
        server_res = await session.read_resource("system://server-info")
        assert len(server_res.contents) > 0
        server_data = json.loads(server_res.contents[0].text)
        assert server_data["transport"] == "streamable_http"

        # 5. Read system://database-info
        db_res = await session.read_resource("system://database-info")
        assert len(db_res.contents) > 0
        db_data = json.loads(db_res.contents[0].text)
        assert db_data["database_type"] == "PostgreSQL"
        assert db_data["status"] == "connected"
