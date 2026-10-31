"""Integration tests for ResearchMate Multi-Agent System (MAS) agents (Phase 9).

Validates end-to-end execution of:
- ResearchAgent invoking File Management tools through MCPHost over Streamable HTTP with real local Ollama.
- TaskAgent invoking Task Management tools through MCPHost over Streamable HTTP with real local Ollama.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import uvicorn

from client_mcp.config import MCPClientSettings
from client_mcp.host import MCPHost
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
from mas.ollama.client import OllamaService
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
        server_name="ResearchMate-AgentIntegration-Test",
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


@pytest.fixture
async def ollama_available() -> bool:
    """Verify local Ollama service and model are available, otherwise skip."""
    service = OllamaService()
    if not await service.check_health():
        pytest.skip("Local Ollama daemon is not running on localhost:11434")
    try:
        await service.ensure_model_available()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Ollama model '{service.model_name}' not available: {exc}")
    return True


async def test_research_agent_real_inference_and_tool_call(
    running_mcp_server: str,
    ollama_available: bool,
) -> None:
    """Verify ResearchAgent uses local Ollama to invoke list_files through MCPHost."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Provide adequate timeout for local CPU inference on 8GB RAM development machine
        from mas.config.settings import OllamaSettings
        from mas.ollama.client import OllamaService

        ollama_service = OllamaService(settings=OllamaSettings(timeout_seconds=180.0))
        agent = ResearchAgent(mcp_host=host, ollama_service=ollama_service)

        res = await agent.run(
            "Please list all files in the documents workspace folder."
        )

        assert res.is_success is True
        assert res.iterations >= 1
        # Model should have invoked list_files
        assert any(tc.tool_name == "list_files" for tc in res.tool_calls)
        assert len(res.content) > 0


async def test_task_agent_real_inference_and_tool_call(
    running_mcp_server: str,
    ollama_available: bool,
) -> None:
    """Verify TaskAgent uses local Ollama to invoke get_tasks through MCPHost."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Provide adequate timeout for local CPU inference on 8GB RAM development machine
        from mas.config.settings import OllamaSettings
        from mas.ollama.client import OllamaService

        ollama_service = OllamaService(settings=OllamaSettings(timeout_seconds=180.0))
        agent = TaskAgent(mcp_host=host, ollama_service=ollama_service)

        res = await agent.run("List the first 2 tasks currently in the system.")

        assert res.is_success is True
        assert res.iterations >= 1
        # Model should have invoked get_tasks or search_tasks
        assert any(
            tc.tool_name in ("get_tasks", "search_tasks") for tc in res.tool_calls
        )
        assert len(res.content) > 0


async def test_task_agent_create_task_inference(
    running_mcp_server: str,
    ollama_available: bool,
) -> None:
    """Verify TaskAgent uses local Ollama to create a task via create_task tool."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        from mas.config.settings import OllamaSettings
        from mas.ollama.client import OllamaService

        ollama_service = OllamaService(settings=OllamaSettings(timeout_seconds=180.0))
        agent = TaskAgent(mcp_host=host, ollama_service=ollama_service)

        res = await agent.run(
            "Create a new task with title 'Draft Methodology Section' and high priority."
        )

        assert res.is_success is True
        assert res.iterations >= 1
        # Model should have called create_task
        assert any(tc.tool_name == "create_task" for tc in res.tool_calls)
        assert len(res.content) > 0


async def test_agent_schema_validation_against_real_mcp_server(
    running_mcp_server: str,
) -> None:
    """Verify BaseAgent validates arguments against real MCP server schemas and catches violations."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_ollama = MagicMock(spec=OllamaService)

        # Turn 1: Model returns invalid argument type for 'limit' against real get_tasks schema
        turn1_msg = MagicMock()
        tc1 = MagicMock()
        tc1.function.name = "get_tasks"
        tc1.function.arguments = {"limit": "invalid_not_an_int"}
        turn1_msg.tool_calls = [tc1]
        turn1_msg.content = None

        # Turn 2: Model handles error and provides final answer
        turn2_msg = MagicMock()
        turn2_msg.tool_calls = None
        turn2_msg.content = (
            "I could not query tasks because the limit parameter was invalid."
        )

        mock_ollama.chat = AsyncMock(
            side_effect=[
                MagicMock(message=turn1_msg),
                MagicMock(message=turn2_msg),
            ]
        )

        agent = TaskAgent(mcp_host=host, ollama_service=mock_ollama)
        res = await agent.run("Show tasks")

        assert res.is_success is False
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].is_error is True
        assert "is not of type 'integer'" in str(res.tool_calls[0].result)


async def test_agent_destructive_intent_safeguard_against_real_mcp_server(
    running_mcp_server: str,
) -> None:
    """Verify BaseAgent blocks delete_task without user deletion intent on real MCP server."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_ollama = MagicMock(spec=OllamaService)

        # Non-destructive prompt: Model tries to call delete_task
        turn1_msg = MagicMock()
        tc1 = MagicMock()
        tc1.function.name = "delete_task"
        tc1.function.arguments = {"task_id": "00000000-0000-0000-0000-000000000000"}
        turn1_msg.tool_calls = [tc1]
        turn1_msg.content = None

        turn2_msg = MagicMock()
        turn2_msg.tool_calls = None
        turn2_msg.content = "I was unable to delete because deletion was not requested."

        mock_ollama.chat = AsyncMock(
            side_effect=[
                MagicMock(message=turn1_msg),
                MagicMock(message=turn2_msg),
            ]
        )

        agent = TaskAgent(mcp_host=host, ollama_service=mock_ollama)
        res = await agent.run("Tell me about task 00000000-0000-0000-0000-000000000000")

        assert res.is_success is False
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].is_error is True
        assert "Destructive operation 'delete_task' was blocked" in str(
            res.tool_calls[0].result
        )


async def test_agent_destructive_intent_safeguard_allows_authorized_deletion_against_real_mcp_server(
    running_mcp_server: str,
) -> None:
    """Verify BaseAgent allows delete_task when user provides affirmative authorization to real MCP server."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Create an actual task on the real MCP server first
        create_res = await host.invoke_tool("create_task", {"title": "Task To Delete"})
        assert create_res.is_error is False
        task_id = create_res.data["task_id"]

        mock_ollama = MagicMock(spec=OllamaService)

        # Authorized prompt: explicit instruction and identifiable target
        turn1_msg = MagicMock()
        tc1 = MagicMock()
        tc1.function.name = "delete_task"
        tc1.function.arguments = {"task_id": task_id}
        turn1_msg.tool_calls = [tc1]
        turn1_msg.content = None

        turn2_msg = MagicMock()
        turn2_msg.tool_calls = None
        turn2_msg.content = f"Deleted task {task_id} on MCP server."

        mock_ollama.chat = AsyncMock(
            side_effect=[
                MagicMock(message=turn1_msg),
                MagicMock(message=turn2_msg),
            ]
        )

        agent = TaskAgent(mcp_host=host, ollama_service=mock_ollama)
        res = await agent.run(f"Please delete task {task_id}.")

        assert res.is_success is True
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].is_error is False
        assert res.tool_calls[0].result.get("success") is True
        assert res.tool_calls[0].result.get("task_id") == task_id
