"""Unit tests for Phase 13 — Agent Prompt Engineering and MCP Tool-Calling Reliability.

Evaluates deterministic behavior, tool selection, argument construction, schema validation,
empty-result handling, error recovery, multi-tool workflows, and security preservation.
"""

from unittest.mock import AsyncMock, MagicMock

from google.genai import types

from client_mcp.host import MCPHost
from client_mcp.models import ToolDescriptor, ToolExecutionResult
from mas.agents.gemini_agent_service import AgentGeminiService
from mas.agents.research_agent.agent import (
    RESEARCH_AGENT_PERMITTED_TOOLS,
    ResearchAgent,
)
from mas.agents.research_agent.prompts import RESEARCH_AGENT_SYSTEM_PROMPT
from mas.agents.task_agent.agent import TASK_AGENT_PERMITTED_TOOLS, TaskAgent
from mas.agents.task_agent.prompts import TASK_AGENT_SYSTEM_PROMPT
from mas.agents.validator import validate_tool_call


def _make_gemini_text_response(text: str) -> MagicMock:
    """Return a MagicMock that looks like a Gemini text-only GenerateContentResponse."""
    response = MagicMock()
    response.text = text
    candidate = MagicMock()
    candidate.content.parts = [types.Part.from_text(text=text)]
    response.candidates = [candidate]
    return response


def _make_gemini_tool_call_response(tool_name: str, tool_args: dict) -> MagicMock:
    """Return a MagicMock that looks like a Gemini function-call GenerateContentResponse."""
    fc_part = types.Part.from_function_call(name=tool_name, args=tool_args)
    candidate = MagicMock()
    candidate.content.parts = [fc_part]
    response = MagicMock()
    response.text = None
    response.candidates = [candidate]
    return response


# ==============================================================================
# 1. Prompt Structure & Schema Accuracy Tests
# ==============================================================================


def test_research_agent_prompt_structure_and_categories() -> None:
    """Verify Research Agent prompt contains all 8 required instruction sections and valid categories."""
    prompt = RESEARCH_AGENT_SYSTEM_PROMPT

    # 8 Required sections
    assert "# Role and Objective" in prompt
    assert "# Core Operating Instructions" in prompt
    assert "# Tool Selection Guidelines" in prompt
    assert "# Tool Argument Construction" in prompt
    assert "# Tool Execution and Response Interpretation" in prompt
    assert "# Error Handling and Recovery" in prompt
    assert "# Security and Authorization Restrictions" in prompt
    assert "# Final Response Requirements" in prompt

    # All 10 permitted tools covered
    for tool_name in RESEARCH_AGENT_PERMITTED_TOOLS:
        assert f"`{tool_name}`" in prompt, (
            f"Tool {tool_name} missing from Research Agent prompt"
        )

    # Valid categories strictly present; invalid category 'literature' must NOT be present
    valid_categories = [
        "general_knowledge",
        "ideas",
        "meeting_notes",
        "personal_notes",
        "project_documentation",
        "technical_research",
    ]
    for cat in valid_categories:
        assert cat in prompt

    # Verify 'literature' is NOT listed as a valid category
    assert "literature," not in prompt
    assert "literature'" not in prompt


def test_task_agent_prompt_structure_and_enums() -> None:
    """Verify Task Agent prompt contains all 8 required sections, all 9 tools, and valid enums."""
    prompt = TASK_AGENT_SYSTEM_PROMPT

    # 8 Required sections
    assert "# Role and Objective" in prompt
    assert "# Core Operating Instructions" in prompt
    assert "# Tool Selection Guidelines" in prompt
    assert "# Tool Argument Construction" in prompt
    assert "# Tool Execution and Response Interpretation" in prompt
    assert "# Error Handling and Recovery" in prompt
    assert "# Security and Authorization Restrictions" in prompt
    assert "# Final Response Requirements" in prompt

    # All 9 permitted tools covered
    for tool_name in TASK_AGENT_PERMITTED_TOOLS:
        assert f"`{tool_name}`" in prompt, (
            f"Tool {tool_name} missing from Task Agent prompt"
        )

    # Enums
    for priority in ["low", "medium", "high", "critical"]:
        assert f"`{priority}`" in prompt
    for status in ["pending", "in_progress", "completed", "cancelled"]:
        assert f"`{status}`" in prompt


# ==============================================================================
# 2. Tool Selection & Argument Construction Tests
# ==============================================================================


def test_argument_construction_for_all_research_tools() -> None:
    """Verify valid argument construction for all 10 Research Agent tools against dynamic schemas."""
    # Simulated discovered schemas from server
    mock_schemas = {
        "list_files": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        "read_file": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
        "search_files": {
            "type": "object",
            "properties": {
                "query": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "file_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "search_content": {"type": "boolean"},
                "directory": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        "get_file_metadata": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
        "create_note": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["title", "content", "category"],
        },
        "get_note": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "include_versions": {"type": "boolean"},
            },
            "required": ["note_id"],
        },
        "get_notes": {
            "type": "object",
            "properties": {
                "category": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "tag": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "limit": {"type": "integer"},
            },
        },
        "update_note": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string"},
                "title": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "content": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["note_id"],
        },
        "delete_note": {
            "type": "object",
            "properties": {"note_id": {"type": "string"}},
            "required": ["note_id"],
        },
        "search_notes": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    }

    test_cases = [
        ("list_files", {"directory": "documents", "limit": 20}),
        ("read_file", {"file_path": "documents/paper.txt"}),
        (
            "search_files",
            {"query": "transformers", "file_type": ".md", "search_content": True},
        ),
        ("get_file_metadata", {"file_path": "datasets/data.csv"}),
        (
            "create_note",
            {
                "title": "Title",
                "content": "Body",
                "category": "technical_research",
                "tags": ["tag1"],
            },
        ),
        (
            "get_note",
            {
                "note_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "include_versions": False,
            },
        ),
        ("get_notes", {"category": "ideas", "limit": 10}),
        (
            "update_note",
            {"note_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d", "content": "Updated"},
        ),
        ("delete_note", {"note_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"}),
        ("search_notes", {"query": "neural networks", "limit": 10}),
    ]

    for tool_name, args in test_cases:
        prompt = (
            "Please delete note 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
            if tool_name == "delete_note"
            else "Standard research inquiry"
        )
        is_valid, err, _cleaned = validate_tool_call(
            tool_name=tool_name,
            arguments=args,
            user_prompt=prompt,
            permitted_tools=RESEARCH_AGENT_PERMITTED_TOOLS,
            discovered_schemas=mock_schemas,
            agent_name="Research Agent",
        )
        assert is_valid is True, f"Tool {tool_name} validation failed: {err}"


def test_argument_construction_for_all_task_tools() -> None:
    """Verify valid argument construction for all 9 Task Agent tools against dynamic schemas."""
    mock_schemas = {
        "create_task": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "status": {"type": "string"},
                "priority": {"type": "string"},
                "assigned_to": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                "due_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "dependencies": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["title"],
        },
        "get_task": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        "get_tasks": {
            "type": "object",
            "properties": {
                "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "priority": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "assigned_agent_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "limit": {"type": "integer"},
            },
        },
        "update_task": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "priority": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "force": {"type": "boolean"},
            },
            "required": ["task_id"],
        },
        "delete_task": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        "search_tasks": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["query"],
        },
        "list_agents": {
            "type": "object",
            "properties": {
                "role": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
        },
        "get_agent_info": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
        "get_agent_tasks": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["agent_id"],
        },
    }

    test_cases = [
        (
            "create_task",
            {
                "title": "Write paper",
                "priority": "high",
                "assigned_to": {"agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"},
            },
        ),
        ("get_task", {"task_id": "e2a4b890-4c31-48e2-b912-11a2f4c78901"}),
        ("get_tasks", {"status": "pending", "priority": "high"}),
        (
            "update_task",
            {
                "task_id": "e2a4b890-4c31-48e2-b912-11a2f4c78901",
                "status": "completed",
                "force": False,
            },
        ),
        ("delete_task", {"task_id": "e2a4b890-4c31-48e2-b912-11a2f4c78901"}),
        ("search_tasks", {"query": "literature review", "status": "in_progress"}),
        ("list_agents", {"role": "research", "status": "active"}),
        ("get_agent_info", {"agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"}),
        (
            "get_agent_tasks",
            {"agent_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "status": "pending"},
        ),
    ]

    for tool_name, args in test_cases:
        prompt = (
            "Please delete task e2a4b890-4c31-48e2-b912-11a2f4c78901"
            if tool_name == "delete_task"
            else "Standard task inquiry"
        )
        is_valid, err, _cleaned = validate_tool_call(
            tool_name=tool_name,
            arguments=args,
            user_prompt=prompt,
            permitted_tools=TASK_AGENT_PERMITTED_TOOLS,
            discovered_schemas=mock_schemas,
            agent_name="Task Agent",
        )
        assert is_valid is True, f"Tool {tool_name} validation failed: {err}"


# ==============================================================================
# 3. Required vs. Optional Parameters & String Null Normalization
# ==============================================================================


def test_required_versus_optional_parameters_validation() -> None:
    """Verify missing required parameters are rejected and optional parameters can be omitted or null."""
    mock_schemas = {
        "read_file": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
        "create_note": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
                "tags": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["title", "content", "category"],
        },
    }

    # 1. Missing required field 'file_path'
    is_valid, err, _ = validate_tool_call(
        tool_name="read_file",
        arguments={},
        user_prompt="Read file",
        permitted_tools={"read_file"},
        discovered_schemas=mock_schemas,
        agent_name="Research Agent",
    )
    assert is_valid is False
    assert "'file_path' is a required property" in err

    # 2. Missing required field 'category' in create_note
    is_valid, err, _ = validate_tool_call(
        tool_name="create_note",
        arguments={"title": "T", "content": "C"},
        user_prompt="Create note",
        permitted_tools={"create_note"},
        discovered_schemas=mock_schemas,
        agent_name="Research Agent",
    )
    assert is_valid is False
    assert "'category' is a required property" in err

    # 3. Optional tags safely omitted -> succeeds
    is_valid, err, cleaned = validate_tool_call(
        tool_name="create_note",
        arguments={"title": "T", "content": "C", "category": "ideas"},
        user_prompt="Create note",
        permitted_tools={"create_note"},
        discovered_schemas=mock_schemas,
        agent_name="Research Agent",
    )
    assert is_valid is True
    assert "tags" not in cleaned

    # 4. Optional tags explicitly null -> safely normalized
    is_valid, err, cleaned = validate_tool_call(
        tool_name="create_note",
        arguments={"title": "T", "content": "C", "category": "ideas", "tags": None},
        user_prompt="Create note",
        permitted_tools={"create_note"},
        discovered_schemas=mock_schemas,
        agent_name="Research Agent",
    )
    assert is_valid is True
    assert cleaned["tags"] is None


# ==============================================================================
# 4. Multi-Tool Workflow Execution (Mocked Inference)
# ==============================================================================


async def test_research_agent_multi_tool_workflow_search_then_read() -> None:
    """Verify Research Agent executes multi-tool workflow: search_files followed by read_file."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="search_files",
                description="Search files",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "file_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
            ),
            ToolDescriptor(
                name="read_file",
                description="Read file",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            ),
        ]
    )

    # Step 1: search_files returns matches
    # Step 2: read_file returns content
    # Step 3: final summary
    turn1 = _make_gemini_tool_call_response(
        "search_files", {"query": "deep learning", "file_type": ".md"}
    )
    turn2 = _make_gemini_tool_call_response(
        "read_file", {"file_path": "reports/deep_learning.md"}
    )
    turn3 = _make_gemini_text_response(
        "Found survey report: Transformers achieve state-of-the-art results."
    )

    mock_gemini = MagicMock(spec=AgentGeminiService)
    mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2, turn3])

    async def fake_invoke(
        name: str, arguments: dict, raise_on_error: bool = False
    ) -> ToolExecutionResult:
        if name == "search_files":
            return ToolExecutionResult(
                tool_name=name,
                data={
                    "total_matches": 1,
                    "matches": [{"file_path": "reports/deep_learning.md"}],
                },
                is_error=False,
            )
        if name == "read_file":
            return ToolExecutionResult(
                tool_name=name,
                data={
                    "file_path": "reports/deep_learning.md",
                    "content": "Transformers achieve SOTA.",
                },
                is_error=False,
            )
        return ToolExecutionResult(
            tool_name=name, data={"error": "Unknown"}, is_error=True
        )

    mock_host.invoke_tool = AsyncMock(side_effect=fake_invoke)

    agent = ResearchAgent(mcp_host=mock_host, gemini_service=mock_gemini)
    response = await agent.run("Find and summarize reports on deep learning")

    assert response.is_success is True
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].tool_name == "search_files"
    assert response.tool_calls[1].tool_name == "read_file"
    assert "Transformers achieve state-of-the-art results" in response.content


async def test_task_agent_multi_tool_workflow_list_agents_then_create_task() -> None:
    """Verify Task Agent executes multi-tool workflow: list_agents then create_task with assigned agent."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="list_agents",
                description="List agents",
                input_schema={
                    "type": "object",
                    "properties": {
                        "role": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "status": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
            ),
            ToolDescriptor(
                name="create_task",
                description="Create task",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "assigned_to": {
                            "anyOf": [{"type": "object"}, {"type": "null"}]
                        },
                    },
                    "required": ["title"],
                },
            ),
        ]
    )

    agent_uuid = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    turn1 = _make_gemini_tool_call_response(
        "list_agents", {"role": "research", "status": "active"}
    )
    turn2 = _make_gemini_tool_call_response(
        "create_task",
        {
            "title": "Review Literature",
            "assigned_to": {"agent_id": agent_uuid},
        },
    )
    turn3 = _make_gemini_text_response(
        f"Created task 'Review Literature' and assigned to Research Agent ({agent_uuid})."
    )

    mock_gemini = MagicMock(spec=AgentGeminiService)
    mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2, turn3])

    async def fake_invoke(
        name: str, arguments: dict, raise_on_error: bool = False
    ) -> ToolExecutionResult:
        if name == "list_agents":
            return ToolExecutionResult(
                tool_name=name,
                data={
                    "total_count": 1,
                    "agents": [
                        {
                            "agent_id": agent_uuid,
                            "name": "Research Agent",
                            "role": "research",
                        }
                    ],
                },
                is_error=False,
            )
        if name == "create_task":
            return ToolExecutionResult(
                tool_name=name,
                data={
                    "task_id": "e2a4b890-4c31-48e2-b912-11a2f4c78901",
                    "title": "Review Literature",
                    "status": "pending",
                },
                is_error=False,
            )
        return ToolExecutionResult(
            tool_name=name, data={"error": "Unknown"}, is_error=True
        )

    mock_host.invoke_tool = AsyncMock(side_effect=fake_invoke)

    agent = TaskAgent(mcp_host=mock_host, gemini_service=mock_gemini)
    response = await agent.run(
        "Assign a new literature review task to an active research agent"
    )

    assert response.is_success is True
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].tool_name == "list_agents"
    assert response.tool_calls[1].tool_name == "create_task"
    assert agent_uuid in response.content


# ==============================================================================
# 5. Empty Result Handling & Error Recovery
# ==============================================================================


async def test_empty_result_handling_no_hallucination() -> None:
    """Verify agents handle empty tool results transparently without hallucinating records."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="search_notes",
                description="Search notes",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]
    )

    turn1 = _make_gemini_tool_call_response(
        "search_notes", {"query": "nonexistent topic"}
    )
    turn2 = _make_gemini_text_response(
        "No research notes were found matching 'nonexistent topic'."
    )

    mock_gemini = MagicMock(spec=AgentGeminiService)
    mock_gemini.chat = AsyncMock(side_effect=[turn1, turn2])

    mock_host.invoke_tool = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="search_notes",
            data={"query": "nonexistent topic", "total_matches": 0, "matches": []},
            is_error=False,
        )
    )

    agent = ResearchAgent(mcp_host=mock_host, gemini_service=mock_gemini)
    response = await agent.run("Find notes about nonexistent topic")

    assert response.is_success is True
    assert len(response.tool_calls) == 1
    assert "No research notes were found" in response.content


async def test_error_recovery_on_validation_feedback() -> None:
    """Verify agent receives validation error feedback and successfully recovers on the next iteration."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="read_file",
                description="Read file",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            )
        ]
    )

    # Iteration 1: Model makes an invalid call missing 'file_path'
    bad_call = _make_gemini_tool_call_response("read_file", {})

    # Iteration 2: Model receives feedback and recovers with valid 'file_path'
    good_call = _make_gemini_tool_call_response(
        "read_file", {"file_path": "documents/report.txt"}
    )

    # Iteration 3: Final answer
    final_turn = _make_gemini_text_response("File content: Research overview.")

    mock_gemini = MagicMock(spec=AgentGeminiService)
    mock_gemini.chat = AsyncMock(side_effect=[bad_call, good_call, final_turn])

    mock_host.invoke_tool = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="read_file",
            data={"file_path": "documents/report.txt", "content": "Research overview."},
            is_error=False,
        )
    )

    agent = ResearchAgent(mcp_host=mock_host, gemini_service=mock_gemini)
    response = await agent.run("Read report.txt in documents")

    # The first tool call failed validation, second succeeded -> overall success is True
    assert response.is_success is True
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].is_error is True
    assert response.tool_calls[1].is_error is False
    assert "Research overview" in response.content


# ==============================================================================
# 6. Avoidance of Unnecessary Tool Calls & Security Whitelist
# ==============================================================================


async def test_avoidance_of_unnecessary_tool_calls_for_greetings() -> None:
    """Verify general conversational requests do not invoke any tools."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(return_value=[])

    mock_gemini = MagicMock(spec=AgentGeminiService)
    greeting_reply = _make_gemini_text_response(
        "Hello! I am your Research Agent. How can I assist you with your academic documents or notes today?"
    )
    mock_gemini.chat = AsyncMock(return_value=greeting_reply)

    agent = ResearchAgent(mcp_host=mock_host, gemini_service=mock_gemini)
    response = await agent.run("Hello, who are you?")

    assert response.is_success is True
    assert len(response.tool_calls) == 0
    assert "Research Agent" in response.content


def test_agent_permission_whitelist_cross_invocation_blocked() -> None:
    """Verify Research Agent cannot call Task Agent tools and vice-versa."""
    mock_schemas = {
        "create_task": {"type": "object", "properties": {"title": {"type": "string"}}},
        "read_file": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
        },
    }

    # Research Agent attempting Task tool
    is_valid, err, _ = validate_tool_call(
        tool_name="create_task",
        arguments={"title": "Unauthorized task"},
        user_prompt="Create task",
        permitted_tools=RESEARCH_AGENT_PERMITTED_TOOLS,
        discovered_schemas=mock_schemas,
        agent_name="Research Agent",
    )
    assert is_valid is False
    assert "Permission denied: Tool 'create_task' is not permitted" in err

    # Task Agent attempting Research tool
    is_valid, err, _ = validate_tool_call(
        tool_name="read_file",
        arguments={"file_path": "documents/file.txt"},
        user_prompt="Read file",
        permitted_tools=TASK_AGENT_PERMITTED_TOOLS,
        discovered_schemas=mock_schemas,
        agent_name="Task Agent",
    )
    assert is_valid is False
    assert "Permission denied: Tool 'read_file' is not permitted" in err
