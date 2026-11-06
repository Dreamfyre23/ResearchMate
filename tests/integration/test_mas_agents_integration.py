"""Integration tests for ResearchMate Multi-Agent System (MAS) agents (DEC-033).

Validates end-to-end execution of:
- ResearchAgent invoking File Management tools through MCPHost over Streamable HTTP
  with mocked Gemini service (real Gemini calls require live API key).
- TaskAgent invoking Task Management tools through MCPHost over Streamable HTTP
  with mocked Gemini service.
- Schema validation against real MCP server schemas.
- Destructive intent safeguard against real MCP server.

DEC-033: Sub-agents run on Google Gemini. Integration tests use a mocked
AgentGeminiService for offline determinism.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import uvicorn
from google.genai import types

from client_mcp.config import MCPClientSettings
from client_mcp.host import MCPHost
from mas.agents.gemini_agent_service import AgentGeminiService
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
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


# ---------------------------------------------------------------------------
# Helpers to build mock Gemini responses
# ---------------------------------------------------------------------------


def _make_gemini_text_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    candidate = MagicMock()
    candidate.content.parts = [types.Part.from_text(text=text)]
    response.candidates = [candidate]
    return response


def _make_gemini_tool_call_response(tool_name: str, tool_args: dict) -> MagicMock:
    fc_part = types.Part.from_function_call(name=tool_name, args=tool_args)
    candidate = MagicMock()
    candidate.content.parts = [fc_part]
    response = MagicMock()
    response.text = None
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# Tests with mocked Gemini + real MCP server
# ---------------------------------------------------------------------------


async def test_research_agent_tool_call_via_mock_gemini(
    running_mcp_server: str,
) -> None:
    """Verify ResearchAgent invokes list_files through a real MCPHost using mocked Gemini."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=AgentGeminiService)

        # Turn 1: Gemini requests list_files
        turn1 = _make_gemini_tool_call_response(
            "list_files", {"directory": "documents"}
        )
        # Turn 2: Gemini produces final text after receiving tool result
        turn2 = _make_gemini_text_response(
            "The documents folder contains the listed files."
        )
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = ResearchAgent(mcp_host=host, gemini_service=mock_gemini)
        res = await agent.run(
            "Please list all files in the documents workspace folder."
        )

        assert res.is_success is True
        assert res.iterations >= 1
        assert any(tc.tool_name == "list_files" for tc in res.tool_calls)
        assert len(res.content) > 0


async def test_task_agent_get_tasks_via_mock_gemini(
    running_mcp_server: str,
) -> None:
    """Verify TaskAgent invokes get_tasks through a real MCPHost using mocked Gemini."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=AgentGeminiService)

        turn1 = _make_gemini_tool_call_response("get_tasks", {"limit": 2})
        turn2 = _make_gemini_text_response("Here are the first 2 tasks in the system.")
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = TaskAgent(mcp_host=host, gemini_service=mock_gemini)
        res = await agent.run("List the first 2 tasks currently in the system.")

        assert res.is_success is True
        assert res.iterations >= 1
        assert any(
            tc.tool_name in ("get_tasks", "search_tasks") for tc in res.tool_calls
        )
        assert len(res.content) > 0


async def test_task_agent_create_task_via_mock_gemini(
    running_mcp_server: str,
) -> None:
    """Verify TaskAgent creates a task through a real MCPHost using mocked Gemini."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=AgentGeminiService)

        turn1 = _make_gemini_tool_call_response(
            "create_task", {"title": "Draft Methodology Section", "priority": "high"}
        )
        turn2 = _make_gemini_text_response(
            "Created task 'Draft Methodology Section' with high priority."
        )
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = TaskAgent(mcp_host=host, gemini_service=mock_gemini)
        res = await agent.run(
            "Create a new task with title 'Draft Methodology Section' and high priority."
        )

        assert res.is_success is True
        assert res.iterations >= 1
        assert any(tc.tool_name == "create_task" for tc in res.tool_calls)
        assert len(res.content) > 0


async def test_agent_schema_validation_against_real_mcp_server(
    running_mcp_server: str,
) -> None:
    """Verify BaseAgent validates arguments against real MCP server schemas and catches violations."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=AgentGeminiService)

        # Model returns invalid argument type for 'limit' against real get_tasks schema
        turn1 = _make_gemini_tool_call_response(
            "get_tasks", {"limit": "invalid_not_an_int"}
        )
        turn2 = _make_gemini_text_response(
            "I could not query tasks because the limit parameter was invalid."
        )
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = TaskAgent(mcp_host=host, gemini_service=mock_gemini)
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
        mock_gemini = MagicMock(spec=AgentGeminiService)

        # Non-destructive prompt: Model tries to call delete_task
        turn1 = _make_gemini_tool_call_response(
            "delete_task", {"task_id": "00000000-0000-0000-0000-000000000000"}
        )
        turn2 = _make_gemini_text_response(
            "I was unable to delete because deletion was not requested."
        )
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = TaskAgent(mcp_host=host, gemini_service=mock_gemini)
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
    """Verify BaseAgent allows delete_task when user provides affirmative authorization."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Create an actual task on the real MCP server first
        create_res = await host.invoke_tool("create_task", {"title": "Task To Delete"})
        assert create_res.is_error is False
        task_id = create_res.data["task_id"]

        mock_gemini = MagicMock(spec=AgentGeminiService)

        # Authorized prompt with explicit target
        turn1 = _make_gemini_tool_call_response("delete_task", {"task_id": task_id})
        turn2 = _make_gemini_text_response(f"Deleted task {task_id}.")
        mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

        agent = TaskAgent(mcp_host=host, gemini_service=mock_gemini)
        res = await agent.run(f"Please delete task {task_id}.")

        assert res.is_success is True
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].is_error is False
        assert res.tool_calls[0].result.get("success") is True
        assert res.tool_calls[0].result.get("task_id") == task_id
