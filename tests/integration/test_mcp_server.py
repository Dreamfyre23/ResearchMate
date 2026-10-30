"""Integration tests for ResearchMate server-side MCP server (Phase 3).

Validates:
- Server configuration loading and overrides.
- Starlette ASGI application creation.
- Diagnostic HTTP endpoints (/health and /status).
- Streamable HTTP protocol connection and handshake via official MCP client.
- Capability discovery (tools and resources).
- Error handling on invalid HTTP requests.
- Graceful server shutdown.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from server_mcp.config import MCPServerSettings, get_server_settings
from server_mcp.server import create_app, create_mcp_server


def _find_free_port() -> int:
    """Find an available TCP port for local server testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server_settings() -> MCPServerSettings:
    """Return default server settings for testing."""
    return get_server_settings()


@pytest.fixture
def test_client(server_settings: MCPServerSettings) -> TestClient:
    """Provide a Starlette TestClient for testing HTTP diagnostic endpoints."""
    app = create_app(server_settings)
    return TestClient(app)


@pytest.fixture
async def running_server() -> AsyncGenerator[tuple[str, int], None]:
    """Start an in-process MCP server on an ephemeral port and yield the base URL."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="Test-MCP-Server",
        server_version="0.1.0-test",
        log_level="warning",
    )
    app = create_app(settings)
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())

    # Wait for server to bind
    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"http://{host}:{port}/health")
                if res.status_code == 200:
                    break
        except (httpx.ConnectError, OSError):
            await asyncio.sleep(0.05)

    yield f"http://{host}:{port}", port

    server.should_exit = True
    await server_task


def test_server_configuration_defaults() -> None:
    """Verify default server configuration values."""
    settings = MCPServerSettings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.mcp_path == "/mcp"
    assert settings.server_name == "ResearchMate-MCP-Server"
    assert settings.server_version == "0.1.0"


def test_server_configuration_override() -> None:
    """Verify server settings can be overridden."""
    settings = MCPServerSettings(
        host="0.0.0.0",
        port=9000,
        mcp_path="/api/mcp",
        server_name="CustomServer",
    )
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.mcp_path == "/api/mcp"
    assert settings.server_name == "CustomServer"


def test_create_mcp_server_instance() -> None:
    """Verify create_mcp_server returns a configured MCPServer instance."""
    server = create_mcp_server()
    assert server.name == "ResearchMate-MCP-Server"
    assert server.version == "0.1.0"


def test_health_check_endpoint(test_client: TestClient) -> None:
    """Verify the /health diagnostic endpoint returns 200 OK and expected JSON."""
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["server"] == "ResearchMate-MCP-Server"
    assert data["version"] == "0.1.0"


def test_status_endpoint(test_client: TestClient) -> None:
    """Verify the /status diagnostic endpoint returns operational state."""
    response = test_client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert data["transport"] == "streamable_http"
    assert data["endpoint"] == "/mcp"
    assert "database" in data
    assert data["database"] in ("connected", "disconnected", "unavailable")


def test_nonexistent_endpoint_returns_404(test_client: TestClient) -> None:
    """Verify unknown routes return standard 404 response."""
    response = test_client.get("/unknown_route")
    assert response.status_code == 404


async def test_mcp_client_handshake_and_discovery(
    running_server: tuple[str, int],
) -> None:
    """Verify official MCP client can connect, initialize handshake, and discover capabilities."""
    base_url, _port = running_server
    mcp_url = f"{base_url}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        # 1. Initialize protocol handshake
        init_result = await session.initialize()
        assert init_result is not None
        assert init_result.server_info.name == "Test-MCP-Server"
        assert init_result.server_info.version == "0.1.0-test"
        assert init_result.protocol_version is not None
        assert init_result.capabilities is not None

        # 2. Verify capability discovery
        tools_result = await session.list_tools()
        assert tools_result is not None
        assert isinstance(tools_result.tools, list)
        assert len(tools_result.tools) == 19
        tool_names = {t.name for t in tools_result.tools}
        assert {
            "get_agent_info",
            "list_agents",
            "get_agent_tasks",
            "create_task",
            "get_task",
            "get_tasks",
            "update_task",
            "delete_task",
            "search_tasks",
            "create_note",
            "get_note",
            "get_notes",
            "update_note",
            "delete_note",
            "search_notes",
            "list_files",
            "read_file",
            "search_files",
            "get_file_metadata",
        }.issubset(tool_names)

        resources_result = await session.list_resources()
        assert resources_result is not None
        assert isinstance(resources_result.resources, list)
        assert len(resources_result.resources) == 19
        resource_uris = {str(r.uri) for r in resources_result.resources}
        assert "system://status" in resource_uris
        assert "system://statistics" in resource_uris
        assert "system://available-tools" in resource_uris
        assert "system://server-info" in resource_uris
        assert "system://database-info" in resource_uris
        assert "agents://all" in resource_uris
        assert "agents://active" in resource_uris
        assert "agents://capabilities" in resource_uris
        assert "tasks://all" in resource_uris
        assert "tasks://pending" in resource_uris
        assert "tasks://in-progress" in resource_uris
        assert "tasks://completed" in resource_uris
        assert "tasks://high-priority" in resource_uris
        assert "notes://all" in resource_uris
        assert "notes://technical" in resource_uris
        assert "notes://research" in resource_uris
        assert "notes://literature" in resource_uris
        assert "notes://project" in resource_uris
        assert "notes://ideas" in resource_uris


async def test_invalid_http_method_on_mcp_endpoint(
    running_server: tuple[str, int],
) -> None:
    """Verify invalid HTTP methods on /mcp return client error without crashing server."""
    base_url, _port = running_server
    mcp_url = f"{base_url}/mcp"

    async with httpx.AsyncClient() as client:
        # PUT is not supported on Streamable HTTP endpoint
        response = await client.put(mcp_url, content=b"invalid")
        assert response.status_code in (400, 405)

        # Server remains healthy and operational
        health_res = await client.get(f"{base_url}/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "healthy"
