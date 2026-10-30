"""Unit tests for ResearchMate Multi-Agent System (MAS) agents (Phase 9).

Validates:
- Architectural boundary: verifies mas/ has zero imports from server_mcp or database.
- Agent permission sets (Research Agent vs Task Agent).
- Permission boundary enforcement (rejecting unauthorized tool calls without forwarding to MCPHost).
- Loop bounding and iteration limits (preventing runaway loops).
- Error handling during inference failures.
- Handling empty prompts.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from client_mcp.host import MCPHost
from client_mcp.models import ToolDescriptor, ToolExecutionResult
from mas.agents.research_agent.agent import (
    RESEARCH_AGENT_PERMITTED_TOOLS,
    ResearchAgent,
)
from mas.agents.task_agent.agent import (
    TASK_AGENT_PERMITTED_TOOLS,
    TaskAgent,
)
from mas.agents.validator import (
    is_deletion_authorized,
    is_note_deletion_authorized,
    is_task_deletion_authorized,
    validate_tool_call,
)
from mas.config.settings import AgentSettings
from mas.ollama.client import OllamaService
from mas.ollama.exceptions import OllamaServiceUnavailableError


def test_mas_architectural_boundary_no_forbidden_imports() -> None:
    """Verify that mas/ strictly does NOT import server_mcp or database internals.

    Enforces DEC-004, DEC-024, and AGENTS.md architectural boundary rules.
    """
    mas_dir = Path(__file__).resolve().parent.parent.parent / "mas"
    py_files = list(mas_dir.rglob("*.py"))
    assert len(py_files) > 0, "No Python files found in mas directory"

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


def test_agent_permitted_tool_sets() -> None:
    """Verify strictly segregated tool permission sets for Research and Task agents."""
    # Research Agent must have file and notes tools, but NO task management tools
    assert "list_files" in RESEARCH_AGENT_PERMITTED_TOOLS
    assert "read_file" in RESEARCH_AGENT_PERMITTED_TOOLS
    assert "create_note" in RESEARCH_AGENT_PERMITTED_TOOLS
    assert "create_task" not in RESEARCH_AGENT_PERMITTED_TOOLS
    assert "delete_task" not in RESEARCH_AGENT_PERMITTED_TOOLS

    # Task Agent must have task and agent info tools, but NO file management tools
    assert "create_task" in TASK_AGENT_PERMITTED_TOOLS
    assert "get_task" in TASK_AGENT_PERMITTED_TOOLS
    assert "list_agents" in TASK_AGENT_PERMITTED_TOOLS
    assert "read_file" not in TASK_AGENT_PERMITTED_TOOLS
    assert "create_note" not in TASK_AGENT_PERMITTED_TOOLS


async def test_agent_rejects_empty_prompt() -> None:
    """Verify agent immediately returns error for empty prompt without calling model."""
    mock_host = MagicMock(spec=MCPHost)
    mock_ollama = MagicMock(spec=OllamaService)

    agent = ResearchAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("   ")

    assert not res.is_success
    assert res.iterations == 0
    assert "Empty request prompt" in str(res.error)
    mock_ollama.chat.assert_not_called()


async def test_agent_permission_boundary_enforcement() -> None:
    """Verify agent rejects unauthorized tool calls locally without forwarding to MCPHost."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(name="read_file", description="Read file", input_schema={}),
            ToolDescriptor(
                name="create_task", description="Create task", input_schema={}
            ),
        ]
    )
    mock_host.invoke_tool = AsyncMock()

    # Model attempts to call unauthorized create_task in Turn 1, then answers in Turn 2
    mock_ollama = MagicMock(spec=OllamaService)

    turn1_msg = MagicMock()
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "create_task"
    mock_tool_call.function.arguments = {"title": "Sneaky Task"}
    turn1_msg.tool_calls = [mock_tool_call]
    turn1_msg.content = None

    turn2_msg = MagicMock()
    turn2_msg.tool_calls = None
    turn2_msg.content = "I could not create the task because I do not have permission."

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
        ]
    )

    agent = ResearchAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("Please create a task for me.")

    assert res.is_success
    assert res.iterations == 2
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].is_error is True
    assert "Permission denied" in str(res.tool_calls[0].result)

    # MCPHost was NEVER invoked with create_task
    mock_host.invoke_tool.assert_not_called()


async def test_agent_iteration_limit_prevents_infinite_loop() -> None:
    """Verify agent terminates execution when max_iterations is reached."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(return_value=[])
    mock_host.invoke_tool = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="list_files", is_error=False, data={"entries": []}
        )
    )

    # Model perpetually returns a tool call
    mock_ollama = MagicMock(spec=OllamaService)
    looping_msg = MagicMock()
    mock_tc = MagicMock()
    mock_tc.function.name = "list_files"
    mock_tc.function.arguments = {"directory": "documents"}
    looping_msg.tool_calls = [mock_tc]
    looping_msg.content = None

    mock_ollama.chat = AsyncMock(return_value=MagicMock(message=looping_msg))

    settings = AgentSettings(max_iterations=3)
    agent = ResearchAgent(
        mcp_host=mock_host,
        ollama_service=mock_ollama,
        agent_settings=settings,
    )

    res = await agent.run("Perpetual loop request")

    assert not res.is_success
    assert res.iterations == 3
    assert "Maximum iteration limit reached" in str(res.error)


async def test_agent_handles_ollama_service_failure() -> None:
    """Verify agent catches Ollama errors and returns safe failure response."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(return_value=[])

    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.chat = AsyncMock(
        side_effect=OllamaServiceUnavailableError("Ollama daemon offline")
    )

    agent = TaskAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("List tasks")

    assert not res.is_success
    assert "Ollama daemon offline" in str(res.error)
    assert "Error executing request via local model" in res.content


def test_affirmative_task_deletion_authorization() -> None:
    """Verify affirmative task deletion instructions with identifiable targets are authorized."""
    authorized_prompts = [
        "Delete task 123.",
        "Please delete the task named Draft Methodology.",
        "Please delete task 123e4567-e89b-12d3-a456-426614174000 completely.",
        "Permanently delete task #42.",
        "Delete the 'Draft Methodology' task.",
        "Delete task with title Draft Methodology Section.",
    ]
    for prompt in authorized_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is True, (
            f"Expected authorized for '{prompt}', got False ({reason})"
        )
        assert reason is None


def test_affirmative_note_deletion_authorization() -> None:
    """Verify affirmative note deletion instructions with identifiable targets are authorized."""
    authorized_prompts = [
        "Delete note 123.",
        "Delete my note about neural networks.",
        "Delete the note titled 'Quarterly Report'.",
        "Please delete note xyz.",
        "Delete the 'Neural Networks' note.",
        "Delete note on machine learning.",
    ]
    for prompt in authorized_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is True, (
            f"Expected authorized for '{prompt}', got False ({reason})"
        )
        assert reason is None


def test_negated_deletion_instructions_rejected() -> None:
    """Verify negated instructions are strictly rejected for both tasks and notes."""
    negated_task_prompts = [
        "Do not delete my task.",
        "Don't delete task 123.",
        "Never delete task 123.",
        "Please do not delete the task.",
        "I don't want to delete task 123.",
    ]
    for prompt in negated_task_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "negated instruction" in (reason or "").lower()

    negated_note_prompts = [
        "I don't want to delete this note.",
        "Do not delete note 123.",
        "Never delete my note about neural networks.",
        "Please do not delete note xyz.",
    ]
    for prompt in negated_note_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "negated instruction" in (reason or "").lower()


def test_questions_about_deletion_rejected() -> None:
    """Verify inquiries and questions about deletion are rejected as non-authorizing."""
    question_task_prompts = [
        "What happens if I delete this task?",
        "Can you explain how task deletion works?",
        "Should I delete this task?",
        "Can you delete task 123?",
        "How do I delete a task?",
    ]
    for prompt in question_task_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "questions or inquiries cannot authorize" in (reason or "").lower()

    question_note_prompts = [
        "Should I delete this note?",
        "What happens if I delete note 123?",
        "Could you explain note deletion?",
        "Could you please delete note 123?",
    ]
    for prompt in question_note_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "questions or inquiries cannot authorize" in (reason or "").lower()


def test_hypothetical_and_conditional_deletion_rejected() -> None:
    """Verify hypothetical and conditional deletion requests are rejected."""
    conditional_task_prompts = [
        "What if I delete task 123?",
        "If I delete this task, what happens?",
        "Delete task 123 if it is completed.",
        "If the task is old, delete it.",
        "In case I delete task 123, will data be preserved?",
    ]
    for prompt in conditional_task_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert (
            "hypothetical or conditional" in (reason or "").lower()
            or "questions or inquiries" in (reason or "").lower()
        )

    conditional_note_prompts = [
        "What if I delete this note?",
        "Assuming I delete note 456, what happens?",
        "Delete note 123 unless it is starred.",
        "Delete note 123 if possible.",
    ]
    for prompt in conditional_note_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert (
            "hypothetical or conditional" in (reason or "").lower()
            or "questions or inquiries" in (reason or "").lower()
        )


def test_quoted_deletion_instructions_rejected() -> None:
    """Verify that deletion instructions mentioned only inside quotes are rejected."""
    quoted_task_prompts = [
        'He said "delete task 123"',
        "The user reported: 'delete task 1'",
        'Why did the prompt say "delete task 42"?',
    ]
    for prompt in quoted_task_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert (
            "quoted text" in (reason or "").lower()
            or "questions or inquiries" in (reason or "").lower()
        )

    quoted_note_prompts = [
        'The documentation states "delete note 456"',
        'He wrote: "delete note xyz"',
    ]
    for prompt in quoted_note_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "quoted text" in (reason or "").lower()


def test_task_cancellation_versus_task_deletion_rejected() -> None:
    """Verify cancellation instructions do NOT authorize task deletion."""
    cancellation_prompts = [
        "Cancel the task.",
        "Cancel task 123.",
        "Please cancel my task.",
        "Cancel task 123e4567-e89b-12d3-a456-426614174000.",
    ]
    for prompt in cancellation_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert (
            "cancellation is a status change, not task deletion"
            in (reason or "").lower()
        )


def test_tag_removal_versus_note_deletion_rejected() -> None:
    """Verify tag or property removal requests do NOT authorize note deletion."""
    tag_removal_prompts = [
        "Remove this tag from the note.",
        "Remove tag urgent from note 123.",
        "Delete tag 'draft' from note 456.",
        "Remove label from note.",
    ]
    for prompt in tag_removal_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert (
            "removing tags, labels, or content attributes is not note deletion"
            in (reason or "").lower()
        )


def test_ambiguous_removal_requests_rejected() -> None:
    """Verify ambiguous requests without entity types or targets are rejected."""
    ambiguous_prompts = [
        "remove this.",
        "delete it.",
        "clean this up.",
        "discard changes.",
        "remove.",
    ]
    for prompt in ambiguous_prompts:
        task_auth, _ = is_task_deletion_authorized(prompt)
        note_auth, _ = is_note_deletion_authorized(prompt)
        assert task_auth is False
        assert note_auth is False


def test_missing_or_unidentifiable_targets_rejected() -> None:
    """Verify explicit deletion commands lacking an identifiable target are rejected."""
    missing_target_task_prompts = [
        "Delete task.",
        "Delete the task.",
        "Delete a task.",
        "Delete my task.",
        "Please delete the tasks.",
    ]
    for prompt in missing_target_task_prompts:
        is_auth, reason = is_task_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "no identifiable task target" in (reason or "").lower()

    missing_target_note_prompts = [
        "Delete note.",
        "Delete the note.",
        "Delete a note.",
        "Delete my note.",
        "Please delete notes.",
    ]
    for prompt in missing_target_note_prompts:
        is_auth, reason = is_note_deletion_authorized(prompt)
        assert is_auth is False, f"Expected rejected for '{prompt}', got True"
        assert "no identifiable note target" in (reason or "").lower()


def test_past_tense_statements_rejected() -> None:
    """Verify past tense statements are rejected as non-authorizing."""
    past_prompts = [
        ("I previously deleted a task.", "task"),
        ("We already deleted task 123.", "task"),
        ("I deleted note xyz yesterday.", "note"),
        ("The note was deleted.", "note"),
    ]
    for prompt, op in past_prompts:
        is_auth, reason = (
            is_task_deletion_authorized(prompt)
            if op == "task"
            else is_note_deletion_authorized(prompt)
        )
        assert is_auth is False
        assert "past deletion" in (reason or "").lower()


def test_is_deletion_authorized_wrapper() -> None:
    """Verify is_deletion_authorized wrapper delegates properly by tool name."""
    assert is_deletion_authorized("Delete task 123.", "delete_task") is True
    assert is_deletion_authorized("Delete note 123.", "delete_note") is True
    assert is_deletion_authorized("Cancel task 123.", "delete_task") is False
    assert is_deletion_authorized("Remove tag from note 123.", "delete_note") is False
    assert is_deletion_authorized("Delete task 123.", "unknown_tool") is False


def test_validate_tool_call_rejects_unknown_tool() -> None:
    """Verify tool call is rejected if tool is not present in MCP catalog."""
    discovered = {"read_file": {"type": "object", "properties": {}}}
    permitted = {"read_file", "unknown_tool"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="unknown_tool",
        arguments={},
        user_prompt="Run unknown tool",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TestAgent",
    )
    assert is_valid is False
    assert "not recognized or available on the MCP server" in (err_msg or "")


def test_validate_tool_call_rejects_unauthorized_tool() -> None:
    """Verify tool call is rejected if tool is not in agent permitted set."""
    discovered = {"create_task": {"type": "object", "properties": {}}}
    permitted = {"read_file"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="create_task",
        arguments={},
        user_prompt="Create task",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="ResearchAgent",
    )
    assert is_valid is False
    assert "Permission denied" in (err_msg or "")
    assert "ResearchAgent" in (err_msg or "")


def test_validate_tool_call_blocks_destructive_tool_without_explicit_intent() -> None:
    """Verify destructive tool calls are blocked when user prompt lacks deletion intent."""
    discovered = {
        "delete_task": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }
    }
    permitted = {"delete_task"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="delete_task",
        arguments={"task_id": "123e4567-e89b-12d3-a456-426614174000"},
        user_prompt="Inspect task 123e4567-e89b-12d3-a456-426614174000",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "Destructive operation 'delete_task' was blocked" in (err_msg or "")


def test_validate_tool_call_allows_destructive_tool_with_explicit_intent() -> None:
    """Verify destructive tool calls proceed when user prompt has explicit deletion intent."""
    discovered = {
        "delete_task": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        }
    }
    permitted = {"delete_task"}

    is_valid, err_msg, cleaned = validate_tool_call(
        tool_name="delete_task",
        arguments={"task_id": "123e4567-e89b-12d3-a456-426614174000"},
        user_prompt="Please delete task 123e4567-e89b-12d3-a456-426614174000 completely.",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is True
    assert err_msg is None
    assert cleaned == {"task_id": "123e4567-e89b-12d3-a456-426614174000"}


def test_validate_tool_call_allows_note_deletion_with_explicit_intent() -> None:
    """Verify delete_note proceeds when user prompt has explicit deletion intent."""
    discovered = {
        "delete_note": {
            "type": "object",
            "properties": {"note_id": {"type": "string"}},
            "required": ["note_id"],
        }
    }
    permitted = {"delete_note"}

    is_valid, err_msg, cleaned = validate_tool_call(
        tool_name="delete_note",
        arguments={"note_id": "note-xyz"},
        user_prompt="Delete note note-xyz.",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="ResearchAgent",
    )
    assert is_valid is True
    assert err_msg is None
    assert cleaned == {"note_id": "note-xyz"}


def test_validate_tool_call_blocks_note_deletion_without_explicit_intent() -> None:
    """Verify delete_note is blocked when user prompt lacks note deletion intent."""
    discovered = {
        "delete_note": {
            "type": "object",
            "properties": {"note_id": {"type": "string"}},
            "required": ["note_id"],
        }
    }
    permitted = {"delete_note"}

    # Tag removal prompt
    is_valid, err_msg, _ = validate_tool_call(
        tool_name="delete_note",
        arguments={"note_id": "note-xyz"},
        user_prompt="Remove this tag from the note.",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="ResearchAgent",
    )
    assert is_valid is False
    assert "Destructive operation 'delete_note' was blocked" in (err_msg or "")


def test_validate_tool_call_rejects_non_object_payload() -> None:
    """Verify tool call rejects non-dict argument payloads."""
    discovered = {
        "create_note": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        }
    }
    permitted = {"create_note"}

    for bad_args in ["invalid string", [1, 2, 3], 42]:
        is_valid, err_msg, _ = validate_tool_call(
            tool_name="create_note",
            arguments=bad_args,
            user_prompt="Create note",
            permitted_tools=permitted,
            discovered_schemas=discovered,
            agent_name="ResearchAgent",
        )
        assert is_valid is False
        assert "Malformed tool arguments" in (err_msg or "")


def test_validate_tool_call_missing_required_arguments() -> None:
    """Verify schema validation catches missing required properties."""
    discovered = {
        "create_task": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title"],
        }
    }
    permitted = {"create_task"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="create_task",
        arguments={"description": "Missing title"},
        user_prompt="Create task",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "'title' is a required property" in (err_msg or "")


def test_validate_tool_call_incorrect_argument_types() -> None:
    """Verify schema validation catches incorrect argument types."""
    discovered = {
        "get_tasks": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
            },
        }
    }
    permitted = {"get_tasks"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="get_tasks",
        arguments={"limit": "not_an_integer"},
        user_prompt="Get tasks",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "is not of type 'integer'" in (err_msg or "")


def test_validate_tool_call_invalid_enum_values() -> None:
    """Verify schema validation catches invalid enum choices."""
    discovered = {
        "create_task": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
            },
            "required": ["title"],
        }
    }
    permitted = {"create_task"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="create_task",
        arguments={"title": "Important Task", "priority": "urgent"},
        user_prompt="Create task",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "'urgent' is not one of" in (err_msg or "")


def test_validate_tool_call_disallows_unexpected_properties() -> None:
    """Verify schema validation catches unexpected properties when additionalProperties=False."""
    discovered = {
        "search_tasks": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    }
    permitted = {"search_tasks"}

    is_valid, err_msg, _ = validate_tool_call(
        tool_name="search_tasks",
        arguments={"query": "test", "extra_prop": "unexpected"},
        user_prompt="Search tasks",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "Additional properties are not allowed" in (err_msg or "")


def test_validate_tool_call_nested_structure_validation() -> None:
    """Verify schema validation checks nested object structures."""
    discovered = {
        "custom_tool": {
            "type": "object",
            "properties": {
                "author": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "id": {"type": "integer"},
                    },
                    "required": ["name", "id"],
                }
            },
            "required": ["author"],
        }
    }
    permitted = {"custom_tool"}

    # Sub-property has wrong type
    is_valid, err_msg, _ = validate_tool_call(
        tool_name="custom_tool",
        arguments={"author": {"name": "Agent", "id": "not_an_int"}},
        user_prompt="Run custom tool",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is False
    assert "is not of type 'integer'" in (err_msg or "")


def test_validate_tool_call_strips_none_for_non_nullable_fields() -> None:
    """Verify tool call sanitizes None values for fields that are not nullable."""
    discovered = {
        "get_tasks": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        }
    }
    permitted = {"get_tasks"}

    # Model explicitly sends None for optional integers
    is_valid, err_msg, cleaned = validate_tool_call(
        tool_name="get_tasks",
        arguments={"limit": None, "offset": 10},
        user_prompt="Get tasks",
        permitted_tools=permitted,
        discovered_schemas=discovered,
        agent_name="TaskAgent",
    )
    assert is_valid is True
    assert err_msg is None
    # 'limit' is stripped so default applies, and 'offset' is preserved
    assert cleaned == {"offset": 10}


async def test_agent_intercepts_schema_violation_and_allows_model_recovery() -> None:
    """Verify agent catches invalid tool arguments and passes feedback to the model."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="create_task",
                description="Create a task",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                    },
                    "required": ["title"],
                },
            )
        ]
    )
    mock_host.invoke_tool = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="create_task",
            is_error=False,
            data={"id": "new-task-1", "title": "Fixed Title"},
        )
    )

    mock_ollama = MagicMock(spec=OllamaService)

    # Turn 1: Model calls create_task with missing 'title'
    turn1_msg = MagicMock()
    tc1 = MagicMock()
    tc1.function.name = "create_task"
    tc1.function.arguments = {}
    turn1_msg.tool_calls = [tc1]
    turn1_msg.content = None

    # Turn 2: Model receives error and calls create_task with valid 'title'
    turn2_msg = MagicMock()
    tc2 = MagicMock()
    tc2.function.name = "create_task"
    tc2.function.arguments = {"title": "Fixed Title"}
    turn2_msg.tool_calls = [tc2]
    turn2_msg.content = None

    # Turn 3: Final answer
    turn3_msg = MagicMock()
    turn3_msg.tool_calls = None
    turn3_msg.content = "Created task successfully."

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
            MagicMock(message=turn3_msg),
        ]
    )

    agent = TaskAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("Create a new task")

    assert res.is_success is True
    assert res.iterations == 3
    assert len(res.tool_calls) == 2

    # Turn 1 tool call was intercepted before calling MCPHost
    assert res.tool_calls[0].is_error is True
    assert "'title' is a required property" in str(res.tool_calls[0].result)

    # Turn 2 tool call passed validation and reached MCPHost
    assert res.tool_calls[1].is_error is False
    assert res.tool_calls[1].result == {"id": "new-task-1", "title": "Fixed Title"}
    mock_host.invoke_tool.assert_called_once_with(
        name="create_task",
        arguments={"title": "Fixed Title"},
        raise_on_error=False,
    )


async def test_agent_blocks_destructive_tool_without_user_intent_e2e() -> None:
    """Verify agent blocks destructive tool call end-to-end without calling MCPHost."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="delete_task",
                description="Delete a task",
                input_schema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            )
        ]
    )
    mock_host.invoke_tool = AsyncMock()

    mock_ollama = MagicMock(spec=OllamaService)

    # Turn 1: Model calls delete_task even though prompt asks for status
    turn1_msg = MagicMock()
    tc1 = MagicMock()
    tc1.function.name = "delete_task"
    tc1.function.arguments = {"task_id": "123"}
    turn1_msg.tool_calls = [tc1]
    turn1_msg.content = None

    # Turn 2: Model handles the blocked response
    turn2_msg = MagicMock()
    turn2_msg.tool_calls = None
    turn2_msg.content = "I cannot delete the task because you did not request deletion."

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
        ]
    )

    agent = TaskAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("What is the status of task 123?")

    assert res.is_success is True
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].is_error is True
    assert "Destructive operation 'delete_task' was blocked" in str(
        res.tool_calls[0].result
    )

    # MCPHost was NEVER invoked
    mock_host.invoke_tool.assert_not_called()


async def test_agent_executes_authorized_destructive_tool_e2e() -> None:
    """Verify agent executes destructive tool end-to-end when user provides affirmative authorization."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="delete_task",
                description="Delete a task",
                input_schema={
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            )
        ]
    )
    mock_host.invoke_tool = AsyncMock(
        return_value=ToolExecutionResult(
            tool_name="delete_task",
            is_error=False,
            data={"status": "deleted", "task_id": "123"},
        )
    )

    mock_ollama = MagicMock(spec=OllamaService)

    turn1_msg = MagicMock()
    tc1 = MagicMock()
    tc1.function.name = "delete_task"
    tc1.function.arguments = {"task_id": "123"}
    turn1_msg.tool_calls = [tc1]
    turn1_msg.content = None

    turn2_msg = MagicMock()
    turn2_msg.tool_calls = None
    turn2_msg.content = "Task 123 has been deleted."

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
        ]
    )

    agent = TaskAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await agent.run("Please delete task 123.")

    assert res.is_success is True
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].is_error is False
    assert res.tool_calls[0].result == {"status": "deleted", "task_id": "123"}

    # MCPHost WAS invoked with valid target
    mock_host.invoke_tool.assert_called_once_with(
        name="delete_task",
        arguments={"task_id": "123"},
        raise_on_error=False,
    )


async def test_unauthorized_agent_destructive_tool_calls_blocked() -> None:
    """Verify agents cannot invoke destructive tools outside their permitted sets."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.discover_tools = AsyncMock(
        return_value=[
            ToolDescriptor(
                name="delete_task", description="Delete task", input_schema={}
            ),
            ToolDescriptor(
                name="delete_note", description="Delete note", input_schema={}
            ),
        ]
    )
    mock_host.invoke_tool = AsyncMock()

    mock_ollama = MagicMock(spec=OllamaService)

    # 1. ResearchAgent attempts delete_task (not permitted)
    turn1_msg = MagicMock()
    tc1 = MagicMock()
    tc1.function.name = "delete_task"
    tc1.function.arguments = {"task_id": "123"}
    turn1_msg.tool_calls = [tc1]
    turn1_msg.content = None

    turn2_msg = MagicMock()
    turn2_msg.tool_calls = None
    turn2_msg.content = "I do not have permission to delete tasks."

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
        ]
    )

    research_agent = ResearchAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res = await research_agent.run("Delete task 123.")

    assert res.is_success is True
    assert res.tool_calls[0].is_error is True
    assert (
        "Permission denied: Tool 'delete_task' is not permitted for Research Agent"
        in str(res.tool_calls[0].result)
    )
    mock_host.invoke_tool.assert_not_called()

    # 2. TaskAgent attempts delete_note (not permitted)
    tc2 = MagicMock()
    tc2.function.name = "delete_note"
    tc2.function.arguments = {"note_id": "xyz"}
    turn1_msg.tool_calls = [tc2]

    mock_ollama.chat = AsyncMock(
        side_effect=[
            MagicMock(message=turn1_msg),
            MagicMock(message=turn2_msg),
        ]
    )

    task_agent = TaskAgent(mcp_host=mock_host, ollama_service=mock_ollama)
    res2 = await task_agent.run("Delete note xyz.")

    assert res2.is_success is True
    assert res2.tool_calls[0].is_error is True
    assert (
        "Permission denied: Tool 'delete_note' is not permitted for Task Agent"
        in str(res2.tool_calls[0].result)
    )
    mock_host.invoke_tool.assert_not_called()
