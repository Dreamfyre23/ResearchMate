"""Integration tests for ResearchMate client-side MCP host (Phase 8).

Validates:
- Connection lifecycle (connect, clean disconnect, idempotence).
- Context manager support (async with MCPHost(...) as host).
- Connection failures to unavailable servers.
- Dynamic capability discovery (tools and resources).
- Tool invocations (valid arguments, invalid arguments, unknown tool, raise_on_error flag).
- Resource reading (valid resource, unknown URI).
- Diagnostic reporting.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator

import httpx
import pytest
import uvicorn

from client_mcp.config import MCPClientSettings
from client_mcp.exceptions import (
    MCPConnectionError,
    MCPResourceError,
    MCPToolError,
)
from client_mcp.host import MCPHost
from server_mcp.config import MCPServerSettings
from server_mcp.server import create_app


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
        server_name="ResearchMate-ClientHost-Test",
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

    base_url = f"http://{host}:{port}"
    yield base_url

    server.should_exit = True
    await server_task


async def test_client_connection_lifecycle_and_idempotence(
    running_mcp_server: str,
) -> None:
    """Verify clean connection, session maintenance, idempotence, and disconnect."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url, timeout_seconds=5.0)
    host = MCPHost(settings=settings)

    assert not host.is_connected

    # Connect
    await host.connect()
    assert host.is_connected
    assert host.client.server_info is not None

    # Idempotent second connect
    await host.connect()
    assert host.is_connected

    # Clean disconnect
    await host.disconnect()
    assert not host.is_connected

    # Idempotent second disconnect
    await host.disconnect()
    assert not host.is_connected


async def test_client_context_manager_lifecycle(running_mcp_server: str) -> None:
    """Verify async context manager connects on enter and disconnects on exit."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url, timeout_seconds=5.0)

    async with MCPHost(settings=settings) as host:
        assert host.is_connected
        tools = await host.discover_tools()
        assert len(tools) > 0

    assert not host.is_connected


async def test_client_connection_failure_to_unavailable_server() -> None:
    """Verify connection attempts to an offline port cleanly raise MCPConnectionError."""
    unused_port = _find_free_port()
    mcp_url = f"http://127.0.0.1:{unused_port}/mcp"
    settings = MCPClientSettings(
        server_url=mcp_url,
        timeout_seconds=0.5,
        max_retries=1,
        retry_delay_seconds=0.05,
    )
    host = MCPHost(settings=settings)

    with pytest.raises(MCPConnectionError) as exc_info:
        await host.connect()

    assert "Failed to connect to MCP server" in str(exc_info.value)
    assert not host.is_connected


async def test_client_dynamic_capability_discovery(running_mcp_server: str) -> None:
    """Verify dynamic discovery of all registered tools and resources."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        # Discover tools
        tools = await host.discover_tools()
        assert len(tools) == 19
        tool_names = {t.name for t in tools}

        expected_tool_names = {
            # Task Management
            "create_task",
            "get_task",
            "get_tasks",
            "update_task",
            "delete_task",
            "search_tasks",
            # Notes Management
            "create_note",
            "get_note",
            "get_notes",
            "update_note",
            "delete_note",
            "search_notes",
            # File Management
            "list_files",
            "read_file",
            "search_files",
            "get_file_metadata",
            # Agent Information
            "get_agent_info",
            "list_agents",
            "get_agent_tasks",
        }
        assert expected_tool_names.issubset(tool_names)

        # Verify tool descriptor fields
        create_task_tool = await host.get_tool("create_task")
        assert create_task_tool is not None
        assert "title" in create_task_tool.input_schema.get("properties", {})

        # Discover resources
        resources = await host.discover_resources()
        assert len(resources) == 19
        resource_uris = {r.uri for r in resources}

        expected_uris = {
            "system://status",
            "system://statistics",
            "system://available-tools",
            "system://server-info",
            "system://database-info",
            "tasks://pending",
            "notes://all",
        }
        assert expected_uris.issubset(resource_uris)

        # Verify resource descriptor fields
        status_res = await host.get_resource("system://status")
        assert status_res is not None
        assert status_res.mime_type == "application/json"


async def test_client_tool_invocation_success_and_structured_result(
    running_mcp_server: str,
) -> None:
    """Verify invoking registered tools returns structured data."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        # 1. Invoke list_agents
        agents_res = await host.invoke_tool("list_agents")
        assert not agents_res.is_error
        assert isinstance(agents_res.data, list)

        # 2. Invoke list_files
        files_res = await host.invoke_tool("list_files", {"directory": "documents"})
        assert not files_res.is_error
        assert isinstance(files_res.data, dict)
        assert files_res.data.get("directory") == "documents"

        # 3. Invoke get_tasks
        tasks_res = await host.invoke_tool("get_tasks", {})
        assert not tasks_res.is_error
        assert isinstance(tasks_res.data, list)


async def test_client_tool_invocation_unknown_tool(running_mcp_server: str) -> None:
    """Verify handling of unknown tool invocations."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        # Default: returns ToolExecutionResult with is_error=True
        result = await host.invoke_tool("nonexistent_dummy_tool", {})
        assert result.is_error

        # With raise_on_error=True: raises MCPToolError
        with pytest.raises(MCPToolError) as exc_info:
            await host.invoke_tool("nonexistent_dummy_tool", {}, raise_on_error=True)

        assert "nonexistent_dummy_tool" in str(exc_info.value)


async def test_client_tool_invocation_invalid_arguments(
    running_mcp_server: str,
) -> None:
    """Verify handling of tool calls with invalid arguments."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        # Attempt to get task with invalid UUID
        result = await host.invoke_tool("get_task", {"task_id": "not-a-valid-uuid"})
        assert result.is_error
        assert "error" in result.data or "UUID" in str(result.data)


async def test_client_resource_reading(running_mcp_server: str) -> None:
    """Verify reading valid resources and handling nonexistent resource URIs."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        # Read system://server-info
        res = await host.read_resource("system://server-info")
        assert res.mime_type == "application/json"
        assert isinstance(res.data, dict)
        assert "server_name" in res.data
        assert res.data["server_name"] in (
            "ResearchMate-MCP-Server",
            "ResearchMate-ClientHost-Test",
        )

        # Read nonexistent resource
        with pytest.raises(MCPResourceError) as exc_info:
            await host.read_resource("system://nonexistent-resource-uri")

        assert "system://nonexistent-resource-uri" in str(exc_info.value)


async def test_client_run_diagnostics(running_mcp_server: str) -> None:
    """Verify run_diagnostics provides comprehensive connectivity and inventory summary."""
    mcp_url = f"{running_mcp_server}/mcp"
    settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=settings) as host:
        diagnostics = await host.run_diagnostics()
        assert diagnostics["connected"] is True
        assert diagnostics["tool_count"] == 19
        assert diagnostics["resource_count"] == 19
        assert "list_files" in diagnostics["tools"]
        assert "system://server-info" in diagnostics["resources"]
