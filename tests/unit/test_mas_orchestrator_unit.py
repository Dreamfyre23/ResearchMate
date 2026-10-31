"""Unit tests for ResearchMate central Gemini-powered orchestrator (Phase 10).

Validates:
- Architectural boundary: mas/orchestrator has zero imports from server_mcp or database.
- Gemini integration: success, error handling, rate limits, timeouts, missing API keys, secret redaction.
- Agent selection: research-only, task-only, independent multi-agent, sequential multi-agent, unsupported requests.
- Delegation contracts: single, independent, sequential with upstream context propagation, bounded delegation steps.
- Failure handling: agent failure, agent timeout, Ollama unavailable, partial failure preservation.
- Response synthesis: transparent reporting without false claims of completion.
"""

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors

from mas.agents.models import AgentRequest, AgentResponse, ToolCallRecord
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
from mas.config.settings import GeminiSettings, OrchestratorSettings
from mas.ollama.exceptions import OllamaServiceUnavailableError
from mas.orchestrator.exceptions import (
    DelegationLimitExceededError,
    GeminiAPIError,
    GeminiConfigurationError,
    GeminiDailyQuotaExhaustedError,
    GeminiRateLimitError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from mas.orchestrator.gemini_service import (
    GeminiFailureCategory,
    GeminiService,
    _redact_secrets,
)
from mas.orchestrator.models import (
    AgentTarget,
    DelegationPlan,
    DelegationResult,
    DelegationTask,
    ExecutionMode,
    ExecutionStatus,
    OrchestratorResponse,
)
from mas.orchestrator.orchestrator import Orchestrator


def test_orchestrator_architectural_boundary_no_forbidden_imports() -> None:
    """Verify that mas/orchestrator strictly does NOT import server_mcp or database internals.

    Enforces DEC-004, DEC-024, and AGENTS.md architectural boundary rules.
    """
    orch_dir = Path(__file__).resolve().parent.parent.parent / "mas" / "orchestrator"
    py_files = list(orch_dir.rglob("*.py"))
    assert len(py_files) > 0, "No Python files found in mas/orchestrator directory"

    forbidden_modules = {"server_mcp", "database"}

    for file_path in py_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    assert top_level not in forbidden_modules, (
                        f"Architecture violation: {file_path.name} imports forbidden module '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level = node.module.split(".")[0]
                assert top_level not in forbidden_modules, (
                    f"Architecture violation: {file_path.name} imports from forbidden module '{node.module}'"
                )


# ==============================================================================
# Gemini Service Tests
# ==============================================================================


def test_gemini_service_missing_api_key_raises_config_error() -> None:
    """Verify GeminiService raises GeminiConfigurationError when API key is missing."""
    settings = GeminiSettings(api_key=None)
    service = GeminiService(settings=settings)

    with pytest.raises(GeminiConfigurationError) as exc_info:
        _ = service.client

    assert "API key is missing" in str(exc_info.value)


def test_gemini_service_redacts_api_key_in_errors() -> None:
    """Verify API keys are strictly redacted from error messages and logs."""
    secret_key = "AIzaSySecretTestKey12345"
    raw_error = (
        f"Failed to connect to Google API with key {secret_key}: connection refused"
    )
    redacted = _redact_secrets(raw_error, secret_key)

    assert secret_key not in redacted
    assert "[REDACTED_API_KEY]" in redacted


async def test_gemini_service_plan_success_parsing() -> None:
    """Verify GeminiService successfully parses valid JSON plan from model."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    ```json
    {
      "reasoning": "User wants to list research notes",
      "mode": "single",
      "tasks": [
        {
          "step_id": "step_1",
          "agent_target": "research_agent",
          "prompt": "List all research notes"
        }
      ]
    }
    ```
    """
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    settings = GeminiSettings(api_key="valid_key")
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("Show me my research notes")

    assert plan.mode == ExecutionMode.SINGLE
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent_target == AgentTarget.RESEARCH_AGENT
    assert plan.tasks[0].prompt == "List all research notes"


async def test_gemini_service_plan_rate_limit_error() -> None:
    """Verify 429 rate limit errors from Gemini API are mapped to GeminiRateLimitError."""
    mock_client = MagicMock()
    api_error = errors.APIError(429, {"error": {"message": "Rate limit exceeded"}})
    mock_client.aio.models.generate_content = AsyncMock(side_effect=api_error)

    settings = GeminiSettings(api_key="valid_key")
    service = GeminiService(settings=settings, client=mock_client)

    with pytest.raises(GeminiRateLimitError):
        await service.plan("Test prompt", use_fallback_on_error=False)


async def test_gemini_service_plan_timeout_error() -> None:
    """Verify Gemini request timeouts raise GeminiTimeoutError."""
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=TimeoutError())

    settings = GeminiSettings(api_key="valid_key", timeout_seconds=0.01)
    service = GeminiService(settings=settings, client=mock_client)

    with pytest.raises(GeminiTimeoutError):
        await service.plan("Test prompt", use_fallback_on_error=False)


async def test_gemini_service_fallback_planning() -> None:
    """Verify deterministic fallback plan classifies requests appropriately."""
    service = GeminiService(settings=GeminiSettings(api_key="test_key"))

    # 1. Research only
    r_plan = service.fallback_plan("Read document summary in workspace")
    assert r_plan.mode == ExecutionMode.SINGLE
    assert r_plan.tasks[0].agent_target == AgentTarget.RESEARCH_AGENT

    # 2. Task only
    t_plan = service.fallback_plan("List all high priority tasks")
    assert t_plan.mode == ExecutionMode.SINGLE
    assert t_plan.tasks[0].agent_target == AgentTarget.TASK_AGENT

    # 3. Multi-agent sequential (contains 'then')
    seq_plan = service.fallback_plan(
        "Read the report files, then create a task for reviewing them"
    )
    assert seq_plan.mode == ExecutionMode.SEQUENTIAL
    assert len(seq_plan.tasks) == 2
    assert seq_plan.tasks[0].agent_target == AgentTarget.RESEARCH_AGENT
    assert seq_plan.tasks[1].agent_target == AgentTarget.TASK_AGENT
    assert seq_plan.tasks[1].depends_on == ["step_1"]

    # 4. Multi-agent independent
    ind_plan = service.fallback_plan("Show my notes and show my tasks")
    assert ind_plan.mode == ExecutionMode.INDEPENDENT
    assert len(ind_plan.tasks) == 2

    # 5. Unsupported
    un_plan = service.fallback_plan("What is the weather in Paris?")
    assert un_plan.mode == ExecutionMode.UNSUPPORTED
    assert len(un_plan.tasks) == 0
    assert "ResearchMate" in (un_plan.direct_response or "")


async def test_gemini_service_synthesize_success() -> None:
    """Verify GeminiService synthesizes final response from agent results."""
    mock_client = MagicMock()
    mock_response = MagicMock(text="Here are your research notes and tasks combined.")
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    settings = GeminiSettings(api_key="valid_key")
    service = GeminiService(settings=settings, client=mock_client)

    plan = DelegationPlan(
        reasoning="Combined query",
        mode=ExecutionMode.INDEPENDENT,
        tasks=[],
    )
    results = [
        DelegationResult(
            step_id="step_1",
            agent_name="Research Agent",
            prompt="Get notes",
            status=ExecutionStatus.SUCCESS,
            content="Found 2 notes.",
        )
    ]

    summary = await service.synthesize("Show notes", plan, results)
    assert summary == "Here are your research notes and tasks combined."


async def test_gemini_service_synthesize_fallback_on_partial_failure() -> None:
    """Verify deterministic fallback synthesis transparently describes partial failures."""
    # Create service with no API key to trigger fallback synthesis
    service = GeminiService(settings=GeminiSettings(api_key=None))

    plan = DelegationPlan(
        reasoning="Multi agent query",
        mode=ExecutionMode.INDEPENDENT,
        tasks=[],
    )
    results = [
        DelegationResult(
            step_id="step_1",
            agent_name="Research Agent",
            prompt="Get notes",
            status=ExecutionStatus.SUCCESS,
            content="Retrieved note on Deep Learning.",
        ),
        DelegationResult(
            step_id="step_2",
            agent_name="Task Agent",
            prompt="Get tasks",
            status=ExecutionStatus.FAILED,
            content="",
            error="Connection timeout to Postgres",
        ),
    ]

    summary = await service.synthesize(
        "Show notes and tasks", plan, results, use_fallback_on_error=True
    )
    assert "Partial Results" in summary
    assert "Deep Learning" in summary
    assert "Incomplete Tasks" in summary
    assert "Connection timeout to Postgres" in summary


# ==============================================================================
# Orchestrator Workflow & Delegation Tests
# ==============================================================================


async def test_orchestrator_handles_empty_prompt() -> None:
    """Verify orchestrator cleanly rejects empty prompts without invoking Gemini."""
    mock_gemini = MagicMock(spec=GeminiService)
    orchestrator = Orchestrator(gemini_service=mock_gemini)

    res: OrchestratorResponse = await orchestrator.run("   ")

    assert res.is_success is False
    assert "Empty prompt" in str(res.errors)
    mock_gemini.plan.assert_not_called()


async def test_orchestrator_unsupported_request_no_agent_invocation() -> None:
    """Verify orchestrator responds directly to unsupported requests without calling agents."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Unsupported chit-chat",
            mode=ExecutionMode.UNSUPPORTED,
            tasks=[],
            direct_response="I am an academic research assistant.",
        )
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_task = MagicMock(spec=TaskAgent)

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("Tell me a funny joke")

    assert res.is_success is True
    assert res.content == "I am an academic research assistant."
    assert len(res.results) == 0
    mock_research.run.assert_not_called()
    mock_task.run.assert_not_called()


async def test_orchestrator_delegates_to_research_agent_single_mode() -> None:
    """Verify orchestrator correctly delegates research-only request to ResearchAgent."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Research note request",
            mode=ExecutionMode.SINGLE,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="List notes with category AI",
                )
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(
        return_value="You have 3 notes under category AI."
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Research Agent",
            content="Found note 1, note 2, note 3.",
            tool_calls=[
                ToolCallRecord(
                    tool_name="get_notes",
                    arguments={"category": "AI"},
                    result={"notes": []},
                )
            ],
            is_success=True,
        )
    )

    mock_task = MagicMock(spec=TaskAgent)

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("List my AI notes")

    assert res.is_success is True
    assert res.content == "You have 3 notes under category AI."
    assert len(res.results) == 1
    assert res.results[0].status == ExecutionStatus.SUCCESS
    assert res.results[0].agent_name == "Research Agent"

    mock_research.run.assert_called_once()
    mock_task.run.assert_not_called()


async def test_orchestrator_delegates_to_task_agent_single_mode() -> None:
    """Verify orchestrator correctly delegates task-only request to TaskAgent."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Task management request",
            mode=ExecutionMode.SINGLE,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt="Create a task for writing the introduction",
                )
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(return_value="Task created successfully.")

    mock_research = MagicMock(spec=ResearchAgent)
    mock_task = MagicMock(spec=TaskAgent)
    mock_task.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Task Agent",
            content="Created task with ID 101.",
            is_success=True,
        )
    )

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("Add a task to write the intro")

    assert res.is_success is True
    assert res.content == "Task created successfully."
    assert len(res.results) == 1
    assert res.results[0].agent_name == "Task Agent"

    mock_task.run.assert_called_once()
    mock_research.run.assert_not_called()


async def test_orchestrator_independent_concurrent_execution() -> None:
    """Verify independent tasks run concurrently across both agents."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Independent notes and tasks query",
            mode=ExecutionMode.INDEPENDENT,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="List notes",
                ),
                DelegationTask(
                    step_id="step_2",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt="List tasks",
                ),
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(
        return_value="Here are your notes and your tasks."
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Research Agent",
            content="Notes: [Note A]",
            is_success=True,
        )
    )

    mock_task = MagicMock(spec=TaskAgent)
    mock_task.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Task Agent",
            content="Tasks: [Task 1]",
            is_success=True,
        )
    )

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("Show notes and tasks")

    assert res.is_success is True
    assert len(res.results) == 2
    mock_research.run.assert_called_once()
    mock_task.run.assert_called_once()


async def test_orchestrator_sequential_delegation_passes_prior_result() -> None:
    """Verify sequential execution propagates findings from step 1 into step 2 prompt."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Sequential research then task creation",
            mode=ExecutionMode.SEQUENTIAL,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="Read paper summary from workspace",
                ),
                DelegationTask(
                    step_id="step_2",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt="Create task based on the paper summary",
                    depends_on=["step_1"],
                ),
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(
        return_value="Read paper summary and created follow-up task."
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Research Agent",
            content="Key finding: Neural network pruning reduces model size by 40%.",
            is_success=True,
        )
    )

    mock_task = MagicMock(spec=TaskAgent)
    captured_task_prompt: list[str] = []

    async def mock_task_run(req: AgentRequest) -> AgentResponse:
        captured_task_prompt.append(req.prompt)
        return AgentResponse(
            agent_name="Task Agent",
            content="Created task: Evaluate 40% pruning methodology.",
            is_success=True,
        )

    mock_task.run = AsyncMock(side_effect=mock_task_run)

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("Read the paper summary and create a follow-up task")

    assert res.is_success is True
    assert len(res.results) == 2

    # Step 2 received Step 1's findings in its prompt
    assert len(captured_task_prompt) == 1
    assert "Neural network pruning reduces model size by 40%" in captured_task_prompt[0]


async def test_orchestrator_enforces_max_delegation_steps() -> None:
    """Verify orchestrator rejects delegation plans that exceed max_delegation_steps."""
    mock_gemini = MagicMock(spec=GeminiService)
    # Formulate plan with 6 tasks when max is 3
    tasks = [
        DelegationTask(
            step_id=f"step_{i}",
            agent_target=AgentTarget.RESEARCH_AGENT,
            prompt=f"Task {i}",
        )
        for i in range(1, 7)
    ]
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Unbounded recursion attempt",
            mode=ExecutionMode.SEQUENTIAL,
            tasks=tasks,
        )
    )

    settings = OrchestratorSettings(max_delegation_steps=3)
    orchestrator = Orchestrator(gemini_service=mock_gemini, settings=settings)

    with pytest.raises(DelegationLimitExceededError) as exc_info:
        await orchestrator.run("Run excessive tasks")

    assert "exceeding maximum limit of 3" in str(exc_info.value)


# ==============================================================================
# Failure Handling & Synthesis Tests
# ==============================================================================


async def test_orchestrator_partial_failure_preserves_successful_results() -> None:
    """Verify orchestrator preserves successful agent output when a second agent fails."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Independent notes and tasks",
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
        return_value=(
            "Partial Results:\n"
            "Research Agent: Deep Learning Fundamentals.\n"
            "Task Agent failed: Database connection timeout."
        )
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Research Agent",
            content="Retrieved note: Deep Learning Fundamentals.",
            is_success=True,
        )
    )

    mock_task = MagicMock(spec=TaskAgent)
    mock_task.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Task Agent",
            content="",
            is_success=False,
            error="Database connection timeout",
        )
    )

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    res = await orchestrator.run("Show notes and tasks")

    assert res.is_success is False
    assert len(res.results) == 2

    # Step 1 succeeded and its output is intact
    assert res.results[0].status == ExecutionStatus.SUCCESS
    assert "Deep Learning Fundamentals" in res.results[0].content

    # Step 2 failed and error is recorded
    assert res.results[1].status == ExecutionStatus.FAILED
    assert "Database connection timeout" in str(res.results[1].error)

    # Synthesis explains partial completion
    assert "Deep Learning Fundamentals" in res.content
    assert "Database connection timeout" in res.content


async def test_orchestrator_agent_timeout_handled_gracefully() -> None:
    """Verify orchestrator catches agent timeout and reports TIMED_OUT status."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Task query",
            mode=ExecutionMode.SINGLE,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt="Query tasks",
                )
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(
        return_value="Task Agent timed out during execution."
    )

    async def hanging_run(_: AgentRequest) -> AgentResponse:
        await asyncio.sleep(2.0)
        return AgentResponse(agent_name="Task Agent", content="Never reached")

    mock_task = MagicMock(spec=TaskAgent)
    mock_task.run = AsyncMock(side_effect=hanging_run)

    settings = OrchestratorSettings(agent_timeout_seconds=0.05)
    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        task_agent=mock_task,
        settings=settings,
    )

    res = await orchestrator.run("Get tasks")

    assert res.is_success is False
    assert len(res.results) == 1
    assert res.results[0].status == ExecutionStatus.TIMED_OUT
    assert "timed out after 0.05s" in str(res.results[0].error)


async def test_orchestrator_handles_ollama_unavailable() -> None:
    """Verify orchestrator handles Ollama daemon unavailable error without crashing."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Research query",
            mode=ExecutionMode.SINGLE,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="Search files",
                )
            ],
        )
    )
    mock_gemini.synthesize = AsyncMock(
        return_value="Execution Failed: Cannot connect to Ollama at localhost:11434"
    )

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        side_effect=OllamaServiceUnavailableError(
            "Cannot connect to Ollama at localhost:11434"
        )
    )

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
    )

    res = await orchestrator.run("Search files")

    assert res.is_success is False
    assert len(res.results) == 1
    assert res.results[0].status == ExecutionStatus.FAILED
    assert "Cannot connect to Ollama" in str(res.results[0].error)
    assert "Execution Failed" in res.content


# ==============================================================================
# Model Configuration & Secret Handling Focused Verification Tests
# ==============================================================================


def test_gemini_model_configuration_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify default Gemini model and environment override behavior."""
    # 1. Default settings
    monkeypatch.delenv("GEMINI_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    default_settings = GeminiSettings(api_key="mock_key", _env_file=None)
    assert default_settings.model in ("gemini-3.5-flash-lite", "gemini-flash-latest")

    # 2. Environment variable override via GEMINI_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    custom_settings = GeminiSettings(api_key="mock_key", _env_file=None)
    assert custom_settings.model == "gemini-3.8-flash"

    # 3. Direct constructor override
    explicit_settings = GeminiSettings(api_key="mock_key", model="gemini-custom-model")
    assert explicit_settings.model == "gemini-custom-model"


async def test_gemini_service_passes_configured_model_to_all_requests() -> None:
    """Verify GeminiService strictly passes configured model to every Gemini API call."""
    mock_client = MagicMock()
    mock_response = MagicMock(
        text='{"reasoning": "test", "mode": "single", "tasks": []}'
    )
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    custom_model = "gemini-3.8-flash"
    settings = GeminiSettings(api_key="test_key", model=custom_model)
    service = GeminiService(settings=settings, client=mock_client)

    # 1. Check plan()
    await service.plan("Test prompt")
    assert (
        mock_client.aio.models.generate_content.call_args.kwargs["model"]
        == custom_model
    )

    # 2. Check synthesize()
    mock_client.aio.models.generate_content.reset_mock()
    mock_client.aio.models.generate_content.return_value = MagicMock(
        text="Synthesized output"
    )
    await service.synthesize(
        "Test prompt",
        DelegationPlan(reasoning="test", mode=ExecutionMode.SINGLE, tasks=[]),
        [],
    )
    assert (
        mock_client.aio.models.generate_content.call_args.kwargs["model"]
        == custom_model
    )


async def test_gemini_service_model_fallback_on_404_error() -> None:
    """Verify model fallback behavior when configured model returns 404 Not Found."""
    mock_client = MagicMock()
    api_error_404 = errors.APIError(
        404, {"error": {"message": "Model not found: gemini-obsolete"}}
    )
    mock_client.aio.models.generate_content = AsyncMock(side_effect=api_error_404)

    settings = GeminiSettings(api_key="valid_key", model="gemini-obsolete")
    service = GeminiService(settings=settings, client=mock_client)

    # With use_fallback_on_error=True, should fallback to deterministic plan
    fallback = await service.plan("Read workspace notes", use_fallback_on_error=True)
    assert fallback.mode == ExecutionMode.SINGLE
    assert fallback.tasks[0].agent_target == AgentTarget.RESEARCH_AGENT

    # With use_fallback_on_error=False, should raise GeminiConfigurationError
    with pytest.raises(GeminiConfigurationError) as exc_info:
        await service.plan("Read workspace notes", use_fallback_on_error=False)
    assert "Gemini model not found" in str(exc_info.value)


def test_secret_redaction_safeguards() -> None:
    """Verify _redact_secrets redacts keys while preserving normal academic/technical text."""
    # 1. Legitimate content untouched
    academic_text = (
        "Analysis of Section 4: Accuracy is 98.5% with alpha=0.05 and beta=0.01."
    )
    assert _redact_secrets(academic_text, api_key="secret123") == academic_text

    # 2. Configured key redacted
    leaked = "Connection failed with key: secret123 in authorization header"
    assert (
        _redact_secrets(leaked, api_key="secret123")
        == "Connection failed with key: [REDACTED_API_KEY] in authorization header"
    )

    # 3. Google API key pattern redacted
    google_key_leak = (
        "API returned error for key AIzaSyD9876543210123456789012345678901 at endpoint"
    )
    redacted = _redact_secrets(google_key_leak, api_key=None)
    assert "AIzaSy" not in redacted
    assert "[REDACTED_API_KEY]" in redacted

    # 4. System prompts contain no credentials or secrets
    from mas.orchestrator.prompts import (
        ORCHESTRATOR_PLANNING_SYSTEM_PROMPT,
        ORCHESTRATOR_SYNTHESIS_SYSTEM_PROMPT,
    )

    for prompt_text in (
        ORCHESTRATOR_PLANNING_SYSTEM_PROMPT,
        ORCHESTRATOR_SYNTHESIS_SYSTEM_PROMPT,
    ):
        assert "AIzaSy" not in prompt_text
        assert "password" not in prompt_text.lower()
        assert "postgresql://" not in prompt_text.lower()


async def test_orchestrator_independent_concurrent_task_cancellation() -> None:
    """Verify cancelling orchestrator.run() terminates running subtasks cleanly."""
    mock_gemini = MagicMock(spec=GeminiService)
    mock_gemini.plan = AsyncMock(
        return_value=DelegationPlan(
            reasoning="Independent tasks",
            mode=ExecutionMode.INDEPENDENT,
            tasks=[
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt="Task 1",
                ),
                DelegationTask(
                    step_id="step_2",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt="Task 2",
                ),
            ],
        )
    )

    started_1 = asyncio.Event()
    started_2 = asyncio.Event()

    async def long_running_1(_: AgentRequest) -> AgentResponse:
        started_1.set()
        await asyncio.sleep(10.0)
        return AgentResponse(agent_name="Research Agent", content="Done")

    async def long_running_2(_: AgentRequest) -> AgentResponse:
        started_2.set()
        await asyncio.sleep(10.0)
        return AgentResponse(agent_name="Task Agent", content="Done")

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(side_effect=long_running_1)
    mock_task = MagicMock(spec=TaskAgent)
    mock_task.run = AsyncMock(side_effect=long_running_2)

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
        task_agent=mock_task,
    )

    orch_task = asyncio.create_task(orchestrator.run("Test concurrency cancellation"))

    await asyncio.wait_for(started_1.wait(), timeout=1.0)
    await asyncio.wait_for(started_2.wait(), timeout=1.0)

    # Cancel orchestrator task
    orch_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await orch_task


# ==============================================================================
# Multi-Model Gemini Fallback System Unit Tests (12 Required Scenarios)
# ==============================================================================


async def test_fallback_scenario_1_primary_model_succeeds_without_fallback() -> None:
    """Scenario 1: Primary model succeeds on first attempt without attempting fallback."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Primary handled", "tasks": [{"step_id": "step_1", "agent_target": "research_agent", "prompt": "Read notes"}]}'
    mock_response = MagicMock(text=plan_json)

    models_called: list[str] = []

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        return mock_response

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="gemini-flash-latest",
        fallback_models="gemini-2.5-flash, gemini-2.0-flash",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("Read notes")

    assert plan.mode == ExecutionMode.SINGLE
    assert len(plan.tasks) == 1
    assert models_called == ["gemini-flash-latest"]


async def test_fallback_scenario_2_primary_quota_exhausted_fallback_1_succeeds() -> (
    None
):
    """Scenario 2: Primary model daily quota exhausted; switches immediately to fallback 1 which succeeds."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Fallback handled", "tasks": [{"step_id": "step_1", "agent_target": "task_agent", "prompt": "Track tasks"}]}'
    mock_response = MagicMock(text=plan_json)

    models_called: list[str] = []

    quota_error = errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota).",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                            }
                        ],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "32000s",
                    },
                ],
            }
        },
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        if model == "gemini-flash-latest":
            raise quota_error
        return mock_response

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="gemini-flash-latest",
        fallback_models="gemini-2.5-flash, gemini-2.0-flash",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("Track tasks")

    assert plan.mode == ExecutionMode.SINGLE
    assert plan.tasks[0].agent_target == AgentTarget.TASK_AGENT
    # Primary model called once with no retry for daily quota; fallback 1 called once
    assert models_called == ["gemini-flash-latest", "gemini-2.5-flash"]
    assert not service.tracker.is_model_available("gemini-flash-latest")
    assert service.tracker.is_model_available("gemini-2.5-flash")


async def test_fallback_scenario_3_primary_and_fallback_1_fail_fallback_2_succeeds() -> (
    None
):
    """Scenario 3: Primary and fallback 1 both fail; fallback 2 succeeds."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Fallback 2 handled", "tasks": [{"step_id": "step_1", "agent_target": "research_agent", "prompt": "Read notes"}]}'
    mock_response = MagicMock(text=plan_json)

    models_called: list[str] = []

    quota_error = errors.APIError(
        429,
        {"error": {"message": "Daily quota exceeded", "status": "RESOURCE_EXHAUSTED"}},
    )
    error_503 = errors.APIError(
        503, {"error": {"message": "Service unavailable", "status": "UNAVAILABLE"}}
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        if model == "model_1":
            raise quota_error
        if model == "model_2":
            raise error_503
        return mock_response

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2, model_3",
        model_retry_attempts=1,
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("Read notes")

    assert plan.mode == ExecutionMode.SINGLE
    # model_1 (quota -> 1 call), model_2 (503 -> 2 calls with 1 retry), model_3 (succeeds -> 1 call)
    assert models_called == ["model_1", "model_2", "model_2", "model_3"]
    assert not service.tracker.is_model_available("model_1")
    assert not service.tracker.is_model_available("model_2")
    assert service.tracker.is_model_available("model_3")


async def test_fallback_scenario_4_all_models_fail_deterministic_fallback_used() -> (
    None
):
    """Scenario 4: All candidate models fail; deterministic fallback planner/synthesis is used."""
    mock_client = MagicMock()
    error_503 = errors.APIError(
        503, {"error": {"message": "Overloaded", "status": "UNAVAILABLE"}}
    )
    mock_client.aio.models.generate_content = AsyncMock(side_effect=error_503)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2",
        model_retry_attempts=0,
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    # 1. With use_fallback_on_error=True (default in orchestrator), returns heuristic plan
    plan = await service.plan(
        "Read document summary in workspace", use_fallback_on_error=True
    )
    assert plan.mode == ExecutionMode.SINGLE
    assert plan.tasks[0].agent_target == AgentTarget.RESEARCH_AGENT

    # 2. With use_fallback_on_error=False, raises GeminiServiceUnavailableError
    service.tracker.clear()
    with pytest.raises(GeminiServiceUnavailableError):
        await service.plan(
            "Read document summary in workspace", use_fallback_on_error=False
        )


async def test_fallback_scenario_5_503_triggers_bounded_retry_and_fallback() -> None:
    """Scenario 5: 503 Overload triggers bounded retry on primary, then switches to fallback."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Fallback handled", "tasks": [{"step_id": "step_1", "agent_target": "task_agent", "prompt": "p"}]}'
    mock_response = MagicMock(text=plan_json)

    models_called: list[str] = []
    error_503 = errors.APIError(
        503, {"error": {"message": "Backend overloaded", "status": "UNAVAILABLE"}}
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        if model == "model_1":
            raise error_503
        return mock_response

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2",
        model_retry_attempts=1,
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("List tasks")

    assert plan.mode == ExecutionMode.SINGLE
    # model_1 retried once (total 2 calls), then model_2 called once and succeeded
    assert models_called == ["model_1", "model_1", "model_2"]


async def test_fallback_scenario_6_timeout_triggers_bounded_retry_and_fallback() -> (
    None
):
    """Scenario 6: Timeout triggers bounded retry on primary, then switches to fallback."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Fallback handled", "tasks": [{"step_id": "step_1", "agent_target": "task_agent", "prompt": "p"}]}'
    mock_response = MagicMock(text=plan_json)

    models_called: list[str] = []

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        if model == "model_1":
            raise TimeoutError("Model 1 timed out")
        return mock_response

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2",
        model_retry_attempts=1,
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    plan = await service.plan("List tasks")

    assert plan.mode == ExecutionMode.SINGLE
    assert models_called == ["model_1", "model_1", "model_2"]


async def test_fallback_scenario_7_invalid_api_key_does_not_trigger_model_switching() -> (
    None
):
    """Scenario 7: Invalid API key (401/403) aborts immediately without attempting fallback models."""
    mock_client = MagicMock()
    models_called: list[str] = []

    auth_error = errors.APIError(
        401, {"error": {"message": "Invalid API Key", "status": "UNAUTHENTICATED"}}
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        raise auth_error

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="bad_key",
        primary_model="model_1",
        fallback_models="model_2, model_3",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    with pytest.raises(GeminiConfigurationError):
        await service.plan("Search notes", use_fallback_on_error=False)

    # model_1 called once; model_2 and model_3 MUST NOT be called
    assert models_called == ["model_1"]


async def test_fallback_scenario_8_invalid_request_400_does_not_trigger_model_switching() -> (
    None
):
    """Scenario 8: Invalid request (400) aborts immediately without attempting fallback models."""
    mock_client = MagicMock()
    models_called: list[str] = []

    bad_req_error = errors.APIError(
        400, {"error": {"message": "Invalid argument", "status": "INVALID_ARGUMENT"}}
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        raise bad_req_error

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2, model_3",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    with pytest.raises(GeminiAPIError):
        await service.plan("Search notes", use_fallback_on_error=False)

    # model_1 called once; model_2 and model_3 MUST NOT be called
    assert models_called == ["model_1"]


async def test_fallback_scenario_9_planning_and_synthesis_can_use_different_models() -> (
    None
):
    """Scenario 9: Planning and synthesis can dynamically utilize different models."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Plan ok", "tasks": [{"step_id": "step_1", "agent_target": "research_agent", "prompt": "p"}]}'

    models_called: list[str] = []
    quota_error = errors.APIError(
        429, {"error": {"message": "Daily limit", "status": "RESOURCE_EXHAUSTED"}}
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        # model_1 fails with quota on planning
        if model == "model_1":
            raise quota_error
        if "agent_results" in contents:
            return MagicMock(text="Synthesis completed by fallback model_2")
        return MagicMock(text=plan_json)

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    # 1. Plan executes: model_1 fails with quota -> model_2 succeeds
    plan = await service.plan("Search workspace notes")
    assert plan.mode == ExecutionMode.SINGLE

    # 2. Synthesize executes: model_1 is tracked as exhausted, so model_2 is called directly!
    results = [
        DelegationResult(
            step_id="step_1",
            agent_name="Research Agent",
            prompt="p",
            status=ExecutionStatus.SUCCESS,
            content="Found relevant file",
        )
    ]
    summary = await service.synthesize("Search workspace notes", plan, results)

    assert "Synthesis completed by fallback model_2" in summary
    # model_1 called once during planning, model_2 called for planning, then model_2 called for synthesis
    assert models_called == ["model_1", "model_2", "model_2"]


async def test_fallback_scenario_10_successful_agent_results_preserved_when_synthesis_fails() -> (
    None
):
    """Scenario 10: Successful agent results are completely preserved when Gemini synthesis fails."""
    mock_gemini = MagicMock(spec=GeminiService)
    plan = DelegationPlan(
        reasoning="Inspect files",
        mode=ExecutionMode.SINGLE,
        tasks=[
            DelegationTask(
                step_id="step_1",
                agent_target=AgentTarget.RESEARCH_AGENT,
                prompt="Read summary notes",
            )
        ],
    )
    mock_gemini.plan = AsyncMock(return_value=plan)

    # Synthesis fails across all Gemini models and falls back to deterministic summary
    agent_output = "Academic report on Transformers retrieved successfully."

    async def fallback_synth(
        user_prompt: str,
        plan: Any,
        results: list[DelegationResult],
        use_fallback_on_error: bool = True,
    ) -> str:
        from mas.orchestrator.gemini_service import _deterministic_fallback_summary

        return _deterministic_fallback_summary(results)

    mock_gemini.synthesize = AsyncMock(side_effect=fallback_synth)

    mock_research = MagicMock(spec=ResearchAgent)
    mock_research.run = AsyncMock(
        return_value=AgentResponse(
            agent_name="Research Agent",
            content=agent_output,
            is_success=True,
            tool_calls=[
                ToolCallRecord(
                    tool_name="read_file",
                    arguments={"path": "notes.md"},
                    result="file content",
                    is_error=False,
                )
            ],
        )
    )

    orchestrator = Orchestrator(
        gemini_service=mock_gemini,
        research_agent=mock_research,
    )

    response = await orchestrator.run("Read summary notes")

    # Verify agent was executed once and succeeded
    assert mock_research.run.call_count == 1
    assert response.is_success is True
    assert len(response.results) == 1
    assert response.results[0].status == ExecutionStatus.SUCCESS
    assert response.results[0].content == agent_output
    # Verify deterministic summary contains exact agent findings
    assert "Research Agent Findings" in response.content
    assert agent_output in response.content


async def test_fallback_scenario_11_exhausted_models_not_repeatedly_called_in_same_execution() -> (
    None
):
    """Scenario 11: Exhausted models are not repeatedly called during the same session/execution."""
    mock_client = MagicMock()
    plan_json = '{"mode": "single", "reasoning": "Plan ok", "tasks": [{"step_id": "step_1", "agent_target": "research_agent", "prompt": "p"}]}'

    models_called: list[str] = []
    quota_error = errors.APIError(
        429,
        {
            "error": {
                "message": "Free tier quota exhausted",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )

    async def fake_generate(model: str, contents: Any, config: Any = None) -> Any:
        models_called.append(model)
        if model == "model_1":
            raise quota_error
        return MagicMock(text=plan_json)

    mock_client.aio.models.generate_content = AsyncMock(side_effect=fake_generate)

    settings = GeminiSettings(
        api_key="valid_key",
        primary_model="model_1",
        fallback_models="model_2",
        model_retry_delay=0.0,
    )
    service = GeminiService(settings=settings, client=mock_client)

    # First request: model_1 fails with quota, model_2 succeeds
    await service.plan("First request")
    assert models_called == ["model_1", "model_2"]

    # Second request: model_1 is tracked as exhausted; model_2 should be called directly!
    await service.plan("Second request")
    assert models_called == ["model_1", "model_2", "model_2"]
    assert models_called.count("model_1") == 1


def test_fallback_scenario_12_duplicate_model_names_in_config_handled_correctly() -> (
    None
):
    """Scenario 12: Duplicate model names, whitespace, and empty entries in config are handled correctly."""
    # 1. Deduplication and whitespace trimming with primary and fallback models
    settings = GeminiSettings(
        api_key="test_key",
        primary_model="gemini-flash-latest",
        fallback_models=" gemini-2.5-flash , gemini-flash-latest , , gemini-2.0-flash , gemini-2.5-flash ",
    )
    assert settings.model_candidates == [
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]

    # 2. Backward compatibility when only GEMINI_MODEL is set (no fallback models)
    legacy_settings = GeminiSettings(
        api_key="test_key",
        model="gemini-1.5-pro",
        fallback_models=None,
    )
    assert legacy_settings.model_candidates == ["gemini-1.5-pro"]

    # 3. Primary model takes precedence over GEMINI_MODEL
    override_settings = GeminiSettings(
        api_key="test_key",
        model="gemini-flash-latest",
        primary_model="gemini-2.5-pro",
        fallback_models=None,
    )
    assert override_settings.model_candidates == ["gemini-2.5-pro"]


def test_classify_gemini_error_various_types() -> None:
    """Verify classify_gemini_error correctly classifies all supported error categories."""
    from mas.orchestrator.gemini_service import classify_gemini_error

    # 1. Timeout
    cat, delay, msg = classify_gemini_error(TimeoutError("Timeout"))
    assert cat == GeminiFailureCategory.TIMEOUT
    assert delay is None

    # 2. Daily quota exhausted with RetryInfo
    err_quota = errors.APIError(
        429,
        {
            "error": {
                "message": "Resource exhausted",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "QuotaFailure",
                        "violations": [{"quotaMetric": "per_day"}],
                    },
                    {"@type": "RetryInfo", "retryDelay": "3600s"},
                ],
            }
        },
    )
    cat, delay, msg = classify_gemini_error(err_quota)
    assert cat == GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED
    assert delay == 3600.0
    assert "Resource exhausted" in msg

    # 3. Rate limited (short burst)
    err_rate = errors.APIError(
        429,
        {
            "error": {
                "message": "Too many requests per minute",
                "status": "RESOURCE_EXHAUSTED",
                "details": [{"@type": "RetryInfo", "retryDelay": "15s"}],
            }
        },
    )
    cat, delay, msg = classify_gemini_error(err_rate)
    assert cat == GeminiFailureCategory.RATE_LIMITED
    assert delay == 15.0
    assert "requests per minute" in msg

    # 4. Auth error 401 / 403
    err_auth = errors.APIError(
        401, {"error": {"message": "Unauthorized", "status": "UNAUTHENTICATED"}}
    )
    cat, delay, msg = classify_gemini_error(err_auth)
    assert cat == GeminiFailureCategory.AUTH_ERROR_401_403
    assert "Unauthorized" in msg

    # 5. Bad request 400
    err_bad = errors.APIError(
        400, {"error": {"message": "Invalid arg", "status": "INVALID_ARGUMENT"}}
    )
    cat, delay, msg = classify_gemini_error(err_bad)
    assert cat == GeminiFailureCategory.INVALID_REQUEST_400
    assert "Invalid arg" in msg

    # 6. Not found 404
    err_404 = errors.APIError(
        404, {"error": {"message": "Model not found", "status": "NOT_FOUND"}}
    )
    cat, delay, msg = classify_gemini_error(err_404)
    assert cat == GeminiFailureCategory.NOT_FOUND_404
    assert "Model not found" in msg

    # 7. Overloaded 503
    err_503 = errors.APIError(
        503, {"error": {"message": "Overloaded", "status": "UNAVAILABLE"}}
    )
    cat, delay, msg = classify_gemini_error(err_503)
    assert cat == GeminiFailureCategory.OVERLOADED_503
    assert "Overloaded" in msg

    # 8. Server error 500
    err_500 = errors.APIError(
        500, {"error": {"message": "Internal error", "status": "INTERNAL"}}
    )
    cat, delay, msg = classify_gemini_error(err_500)
    assert cat == GeminiFailureCategory.SERVER_ERROR_5XX
    assert "Internal error" in msg

    # 9. GeminiDailyQuotaExhaustedError instance
    err_daily = GeminiDailyQuotaExhaustedError("Daily quota exhausted")
    cat, delay, msg = classify_gemini_error(err_daily)
    assert cat == GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED
    assert "Daily quota exhausted" in msg


def test_model_health_tracker_lifecycle() -> None:
    """Verify ModelHealthTracker cooldown, recording, and recovery lifecycle."""
    from mas.orchestrator.gemini_service import ModelHealthTracker

    tracker = ModelHealthTracker()
    assert tracker.is_model_available("gemini-2.5-flash") is True

    # Record failure with short cooldown
    tracker.record_failure(
        "gemini-2.5-flash",
        GeminiFailureCategory.OVERLOADED_503,
        retry_after=0.05,
        error_message="503 Overloaded",
    )
    assert tracker.is_model_available("gemini-2.5-flash") is False
    assert tracker.get_failure_record("gemini-2.5-flash") is not None

    # Wait for cooldown to expire
    import time

    time.sleep(0.06)
    assert tracker.is_model_available("gemini-2.5-flash") is True

    # Record failure and clear via record_success
    tracker.record_failure(
        "gemini-2.5-flash",
        GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED,
        retry_after=100.0,
    )
    assert tracker.is_model_available("gemini-2.5-flash") is False
    tracker.record_success("gemini-2.5-flash")
    assert tracker.is_model_available("gemini-2.5-flash") is True
