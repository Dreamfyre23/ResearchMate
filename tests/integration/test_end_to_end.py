"""End-to-end integration tests for ResearchMate (Phase 11).

Validates complete application workflows across:
User -> CLI -> Gemini Orchestrator -> Research Agent / Task Agent -> MCPHost -> MCP Server -> PostgreSQL / Workspace.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import uvicorn

from client_mcp.config import MCPClientSettings
from client_mcp.host import MCPHost
from mas.agents.models import AgentResponse
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
from mas.cli import ResearchMateCLI
from mas.lifecycle import run_preflight_checks
from mas.orchestrator.conversation import ConversationManager
from mas.orchestrator.gemini_service import GeminiService
from mas.orchestrator.models import (
    AgentTarget,
    DelegationPlan,
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
        server_name="ResearchMate-E2E-Test",
        server_version="0.1.0-e2e",
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


# ==============================================================================
# Complete Application Workflow Tests
# ==============================================================================


async def test_e2e_preflight_checks_with_running_server(
    running_mcp_server: str,
) -> None:
    """Verify pre-flight health checks pass when MCP server is online."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        health = await run_preflight_checks(host=host, server_url=mcp_url)
        assert health.workspace is True
        assert health.mcp_server is True
        assert health.database is True
        assert health.is_operational is True


async def test_e2e_research_agent_workflow(
    running_mcp_server: str,
) -> None:
    """Verify complete Research Agent workflow through CLI/Orchestrator accessing real MCP tools."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Pre-seed a test note via MCP
        create_res = await host.invoke_tool(
            "create_note",
            {
                "title": "Quantum Computing Fundamentals",
                "content": "Qubits exhibit superposition and entanglement.",
                "category": "technical_research",
                "tags": ["quantum", "physics"],
            },
        )
        assert not create_res.is_error

        # Configure deterministic plan to route to Research Agent
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="User wants research notes on quantum",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.RESEARCH_AGENT,
                        prompt="Find notes about quantum",
                    )
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Found note: Quantum Computing Fundamentals discussing superposition."
        )

        # Agent runner executing real tool calls against running MCP server
        async def research_runner(_req):
            res = await host.invoke_tool("search_notes", {"query": "Quantum"})
            notes = res.data if isinstance(res.data, list) else []
            return AgentResponse(
                agent_name="Research Agent",
                content=f"Found {len(notes)} note: {notes[0]['title'] if notes else 'None'}",
                is_success=not res.is_error,
            )

        mock_research = MagicMock(spec=ResearchAgent)
        mock_research.run = AsyncMock(side_effect=research_runner)

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            research_agent=mock_research,
        )
        cli = ResearchMateCLI(mcp_host=host, orchestrator=orchestrator)

        # Run via CLI execute_turn
        res = await cli.execute_turn("Show notes on quantum computing")

        assert res.is_success is True
        assert len(res.results) == 1
        assert res.results[0].status == ExecutionStatus.SUCCESS
        assert "Quantum Computing Fundamentals" in res.results[0].content
        assert "Quantum Computing Fundamentals" in res.content


async def test_e2e_task_agent_workflow(
    running_mcp_server: str,
) -> None:
    """Verify complete Task Agent workflow creating and listing tasks through real MCP tools."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="User wants to track milestone",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.TASK_AGENT,
                        prompt="Create task for experiment",
                    )
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Successfully created task: Run Benchmarks."
        )

        async def task_runner(_req):
            res = await host.invoke_tool(
                "create_task",
                {
                    "title": "Run Benchmarks",
                    "description": "Execute throughput tests",
                    "priority": "high",
                },
            )
            return AgentResponse(
                agent_name="Task Agent",
                content=f"Created task ID: {res.data.get('task_id')}",
                is_success=not res.is_error,
            )

        mock_task = MagicMock(spec=TaskAgent)
        mock_task.run = AsyncMock(side_effect=task_runner)

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            task_agent=mock_task,
        )
        cli = ResearchMateCLI(mcp_host=host, orchestrator=orchestrator)

        res = await cli.execute_turn("Create high priority task to run benchmarks")

        assert res.is_success is True
        assert len(res.results) == 1
        assert res.results[0].status == ExecutionStatus.SUCCESS

        # Verify task is genuinely persisted in PostgreSQL via MCP
        verify_res = await host.invoke_tool("get_tasks", {"limit": 10})
        assert not verify_res.is_error
        tasks = verify_res.data if isinstance(verify_res.data, list) else []
        assert any(t.get("title") == "Run Benchmarks" for t in tasks)


async def test_e2e_multi_agent_workflow_both_agents(
    running_mcp_server: str,
) -> None:
    """Verify independent multi-agent workflow coordinating both Research and Task agents."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="User wants notes and tasks",
                mode=ExecutionMode.INDEPENDENT,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.RESEARCH_AGENT,
                        prompt="Get notes",
                    ),
                    DelegationTask(
                        step_id="step_2",
                        agent_target=AgentTarget.TASK_AGENT,
                        prompt="Get tasks",
                    ),
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Synthesis: All research notes and pending tasks compiled."
        )

        async def research_runner(_req):
            res = await host.invoke_tool("get_notes", {"limit": 5})
            return AgentResponse(
                agent_name="Research Agent",
                content=f"Notes: {len(res.data) if isinstance(res.data, list) else 0}",
                is_success=not res.is_error,
            )

        async def task_runner(_req):
            res = await host.invoke_tool("get_tasks", {"limit": 5})
            return AgentResponse(
                agent_name="Task Agent",
                content=f"Tasks: {len(res.data) if isinstance(res.data, list) else 0}",
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
        cli = ResearchMateCLI(mcp_host=host, orchestrator=orchestrator)

        res = await cli.execute_turn("Summarize research notes and current tasks")

        assert res.is_success is True
        assert len(res.results) == 2
        assert res.results[0].status == ExecutionStatus.SUCCESS
        assert res.results[1].status == ExecutionStatus.SUCCESS


async def test_e2e_multi_turn_conversation_context_preservation(
    running_mcp_server: str,
) -> None:
    """Verify multi-turn conversation maintains context across consecutive user queries."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        captured_contexts: list[dict] = []

        class MockGeminiCapturingService(GeminiService):
            async def plan(self, user_prompt, context=None, use_fallback_on_error=True):
                captured_contexts.append(context or {})
                return DelegationPlan(
                    reasoning="Multi-turn step",
                    mode=ExecutionMode.SINGLE,
                    tasks=[
                        DelegationTask(
                            step_id="step_1",
                            agent_target=AgentTarget.RESEARCH_AGENT,
                            prompt=user_prompt,
                        )
                    ],
                )

            async def synthesize(
                self, user_prompt, plan, results, use_fallback_on_error=True
            ):
                return f"Answer for: {user_prompt}"

        mock_gemini = MockGeminiCapturingService(settings=None)
        mock_research = MagicMock(spec=ResearchAgent)
        mock_research.run = AsyncMock(
            return_value=AgentResponse(
                agent_name="Research Agent", content="Information", is_success=True
            )
        )

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            research_agent=mock_research,
        )
        conversation_manager = ConversationManager(max_history_turns=3)
        cli = ResearchMateCLI(
            mcp_host=host,
            orchestrator=orchestrator,
            conversation_manager=conversation_manager,
        )

        # Turn 1
        res1 = await cli.execute_turn("What papers discuss attention mechanisms?")
        assert res1.is_success is True
        assert conversation_manager.turn_count == 1
        # In Turn 1, no prior context existed
        assert captured_contexts[0].get("conversation_history") is None

        # Turn 2
        res2 = await cli.execute_turn("Summarize the main equation from that paper.")
        assert res2.is_success is True
        assert conversation_manager.turn_count == 2
        # In Turn 2, Turn 1's user query and response were preserved in context
        assert (
            "What papers discuss attention mechanisms?"
            in captured_contexts[1]["conversation_history"]
        )


async def test_e2e_workspace_file_operations(
    running_mcp_server: str,
    tmp_path: Path,
) -> None:
    """Verify workspace file operations work end-to-end through real MCP tools."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Create a real file in the workspace
        workspace_dir = Path("workspace") / "documents"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        test_file = workspace_dir / "e2e_sample_experiment.md"
        test_file.write_text(
            "# Experiment Results\nAccuracy: 95.8%\nLatency: 12ms", encoding="utf-8"
        )

        try:
            # Query file listing through MCP
            list_res = await host.invoke_tool("list_files", {"directory": "documents"})
            assert not list_res.is_error
            entries = list_res.data.get("entries", [])
            assert any(
                item.get("name") == "e2e_sample_experiment.md" for item in entries
            )

            # Read file through MCP
            read_res = await host.invoke_tool(
                "read_file", {"file_path": "documents/e2e_sample_experiment.md"}
            )
            assert not read_res.is_error
            assert "Accuracy: 95.8%" in read_res.data.get("content", "")
        finally:
            if test_file.exists():
                test_file.unlink()


# ==============================================================================
# Negative and Service Unavailable Scenarios
# ==============================================================================


async def test_e2e_mcp_server_unavailable_handled_gracefully() -> None:
    """Verify CLI handles unavailable MCP server with clear error and zero dangling resources."""
    # Point to an unused local port
    unused_port = _find_free_port()
    client_settings = MCPClientSettings(
        server_url=f"http://127.0.0.1:{unused_port}/mcp"
    )
    host = MCPHost(settings=client_settings)

    cli = ResearchMateCLI(mcp_host=host)
    # Attempting to run a query when server is down should return code 1 cleanly
    exit_code = await cli.run_single_query("Test query when server is dead")

    assert exit_code == 1
    assert not host.is_connected


async def test_e2e_agent_service_unavailable_reports_clear_error(
    running_mcp_server: str,
) -> None:
    """Verify orchestrator reports agent failure when sub-agent service is unavailable without crashing application."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            return_value=DelegationPlan(
                reasoning="Task query",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.TASK_AGENT,
                        prompt="Get tasks",
                    )
                ],
            )
        )
        mock_gemini.synthesize = AsyncMock(
            return_value="Task Agent failed: Gemini API service unavailable for sub-agent."
        )

        from mas.agents.gemini_agent_service import AgentGeminiServiceUnavailableError

        mock_task = MagicMock(spec=TaskAgent)
        mock_task.run = AsyncMock(
            side_effect=AgentGeminiServiceUnavailableError(
                "Cannot connect to Gemini API for sub-agent"
            )
        )

        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=mock_gemini,
            task_agent=mock_task,
        )
        cli = ResearchMateCLI(mcp_host=host, orchestrator=orchestrator)

        res = await cli.execute_turn("List my tasks")

        assert res.is_success is False
        assert len(res.results) == 1
        assert res.results[0].status == ExecutionStatus.FAILED
        assert "Cannot connect to Gemini API" in str(res.results[0].error)
        assert "service unavailable" in res.content.lower()


async def test_e2e_gemini_unavailable_uses_deterministic_fallback(
    running_mcp_server: str,
) -> None:
    """Verify orchestrator falls back to deterministic planning when Gemini API is unavailable."""
    mcp_url = f"{running_mcp_server}/mcp"
    client_settings = MCPClientSettings(server_url=mcp_url)

    async with MCPHost(settings=client_settings) as host:
        # Gemini service that fails on plan()
        mock_gemini = MagicMock(spec=GeminiService)
        mock_gemini.plan = AsyncMock(
            side_effect=Exception("Gemini remote endpoint connection refused")
        )
        # fallback_plan is called when plan fails
        fallback_plan = DelegationPlan(
            reasoning="Deterministic fallback for research query",
            mode=ExecutionMode.SINGLE,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="Read workspace files",
                )
            ],
        )
        mock_gemini.fallback_plan.return_value = fallback_plan
        mock_gemini.synthesize = AsyncMock(return_value="Synthesized fallback result.")

        mock_research = MagicMock(spec=ResearchAgent)
        mock_research.run = AsyncMock(
            return_value=AgentResponse(
                agent_name="Research Agent",
                content="Files read successfully.",
                is_success=True,
            )
        )

        # GeminiService fallback enabled
        service = GeminiService(settings=None)
        orchestrator = Orchestrator(
            mcp_host=host,
            gemini_service=service,
            research_agent=mock_research,
        )

        # When Gemini has no API key, plan() falls back to fallback_plan
        res = await orchestrator.run("Read document notes in workspace")

        assert res.is_success is True
        assert res.plan.mode == ExecutionMode.SINGLE
        assert res.results[0].agent_name == "Research Agent"
