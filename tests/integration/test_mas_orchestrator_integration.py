"""Integration tests for ResearchMate central orchestrator (Phase 10).

Validates:
- End-to-end orchestration with running MCP server.
- Live Gemini API interaction when configured in .env.
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
from mas.agents.models import AgentResponse
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
from mas.config.settings import get_gemini_settings
from mas.orchestrator.exceptions import (
    GeminiRateLimitError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from mas.orchestrator.gemini_service import GeminiService
from mas.orchestrator.models import (
    AgentTarget,
    DelegationPlan,
    DelegationResult,
    DelegationTask,
    ExecutionMode,
    ExecutionStatus,
)
from mas.orchestrator.orchestrator import Orchestrator
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
        server_name="ResearchMate-OrchestratorIntegration-Test",
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


async def test_orchestrator_end_to_end_with_mcp_host(
    running_mcp_server: str,
) -> None:
    """Verify Orchestrator initializes agents with real MCPHost and executes plan."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="Show notes in system",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.RESEARCH_AGENT,
                        prompt="Get notes",
                    )
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Synthesized research report from MCP tools."
        )

        mock_research = MagicMock(spec=ResearchAgent)
        mock_research.run = AsyncMock(
            return_value=AgentResponse(
                agent_name="Research Agent",
                content="Note: MCP Protocol Overview",
                is_success=True,
            )
        )

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            research_agent=mock_research,
        )

        res = await orchestrator.run("List research notes")

        assert res.is_success is True
        assert res.content == "Synthesized research report from MCP tools."
        assert len(res.results) == 1
        assert res.results[0].status == ExecutionStatus.SUCCESS
        assert res.results[0].agent_name == "Research Agent"


async def test_shared_mcp_host_concurrent_operations(
    running_mcp_server: str,
) -> None:
    """Verify that multiple concurrent operations on a shared MCPHost session are thread/coroutine safe."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Execute 4 distinct tool calls concurrently through the same connection
        r_files, r_tasks, r_notes, r_agents = await asyncio.gather(
            host.invoke_tool("list_files", {"relative_path": ""}),
            host.invoke_tool("get_tasks", {"limit": 5}),
            host.invoke_tool("get_notes", {"limit": 5}),
            host.invoke_tool("list_agents", {}),
        )

        assert not r_files.is_error
        assert not r_tasks.is_error
        assert not r_notes.is_error
        assert not r_agents.is_error

        assert isinstance(r_files.data, (dict, list))
        assert isinstance(r_tasks.data, (dict, list))
        assert isinstance(r_notes.data, (dict, list))
        assert isinstance(r_agents.data, (dict, list))


async def test_shared_mcp_host_concurrent_with_one_tool_failure(
    running_mcp_server: str,
) -> None:
    """Verify failure in one concurrent tool call does not corrupt the shared MCP session."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # One valid tool call, one invalid tool call (missing required or bad payload)
        valid_res, invalid_res = await asyncio.gather(
            host.invoke_tool("list_files", {"relative_path": ""}),
            host.invoke_tool("get_task", {"task_id": "not-a-valid-uuid"}),
        )

        # Valid call succeeded
        assert not valid_res.is_error
        # Invalid call failed gracefully
        assert invalid_res.is_error

        # Session is still healthy and operational for subsequent calls
        followup = await host.invoke_tool("get_notes", {"limit": 1})
        assert not followup.is_error


async def test_orchestrator_independent_concurrent_execution_with_shared_mcp(
    running_mcp_server: str,
) -> None:
    """Verify Orchestrator runs independent agents concurrently sharing the real MCPHost."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="Independent notes and tasks search",
                mode=ExecutionMode.INDEPENDENT,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.RESEARCH_AGENT,
                        prompt="Find notes",
                    ),
                    DelegationTask(
                        step_id="step_2",
                        agent_target=AgentTarget.TASK_AGENT,
                        prompt="Find tasks",
                    ),
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Notes and tasks retrieved concurrently via MCP."
        )

        # Mock agent run methods that both invoke real MCP tools through the shared host
        async def research_runner(_req):
            res = await host.invoke_tool("list_files", {"relative_path": ""})
            return AgentResponse(
                agent_name="Research Agent",
                content=f"Files found: {len(res.data.get('items', []))}",
                is_success=not res.is_error,
            )

        async def task_runner(_req):
            res = await host.invoke_tool("get_tasks", {"limit": 5})
            task_count = len(res.data) if isinstance(res.data, list) else 0
            return AgentResponse(
                agent_name="Task Agent",
                content=f"Tasks found: {task_count}",
                is_success=not res.is_error,
            )

        mock_research = MagicMock(spec=ResearchAgent)
        mock_research.run = AsyncMock(side_effect=research_runner)

        mock_task = MagicMock(spec=TaskAgent)
        mock_task.run = AsyncMock(side_effect=task_runner)

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            research_agent=mock_research,
            task_agent=mock_task,
        )

        res = await orchestrator.run("Search notes and tasks concurrently")

        assert res.is_success is True
        assert len(res.results) == 2
        assert res.results[0].status == ExecutionStatus.SUCCESS
        assert res.results[1].status == ExecutionStatus.SUCCESS
        assert "Files found" in res.results[0].content
        assert "Tasks found" in res.results[1].content


@pytest.mark.live_gemini
async def test_live_gemini_service_plan_and_synthesize() -> None:
    """Live API integration test against Google Gemini API using real credentials."""
    settings = get_gemini_settings()
    if not settings.api_key or settings.api_key == "replace_with_your_api_key":
        pytest.skip("No real GOOGLE_API_KEY configured in environment or .env")

    service = GeminiService(settings=settings)

    # 1. Test live planning
    try:
        plan = await service.plan(
            "Please read the research notes regarding deep learning and list high priority tasks"
        )
    except (
        GeminiServiceUnavailableError,
        GeminiRateLimitError,
        GeminiTimeoutError,
    ) as exc:
        pytest.skip(f"Live Gemini API temporarily unavailable: {exc}")

    assert plan.mode in (
        ExecutionMode.INDEPENDENT,
        ExecutionMode.SEQUENTIAL,
        ExecutionMode.SINGLE,
    )
    assert len(plan.tasks) >= 1
    assert any(
        t.agent_target in (AgentTarget.RESEARCH_AGENT, AgentTarget.TASK_AGENT)
        for t in plan.tasks
    )

    # 2. Test live synthesis
    mock_results = [
        DelegationResult(
            step_id="step_1",
            agent_name="Research Agent",
            prompt="Find notes",
            status=ExecutionStatus.SUCCESS,
            content="Found note on Transformer Attention Mechanisms.",
        ),
        DelegationResult(
            step_id="step_2",
            agent_name="Task Agent",
            prompt="Find tasks",
            status=ExecutionStatus.SUCCESS,
            content="Task #1: Submit conference draft by Friday.",
        ),
    ]

    synthesis = await service.synthesize(
        user_prompt="Give me a status summary",
        plan=plan,
        results=mock_results,
    )

    assert len(synthesis) > 0
    # Response should mention the key findings
    assert (
        "Transformer" in synthesis
        or "conference" in synthesis
        or "draft" in synthesis
        or "note" in synthesis.lower()
    )
