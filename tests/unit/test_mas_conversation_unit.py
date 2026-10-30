"""Unit tests for multi-turn conversation manager (Phase 11)."""

from mas.orchestrator.conversation import ConversationManager, ConversationTurn
from mas.orchestrator.models import (
    DelegationPlan,
    ExecutionMode,
    OrchestratorResponse,
)


def test_conversation_manager_initial_state() -> None:
    """Verify clean initial state of ConversationManager."""
    manager = ConversationManager(max_history_turns=3, max_summary_chars=100)
    assert manager.turn_count == 0
    assert manager.get_context_summary() == ""
    assert manager.get_context_dict() == {}
    assert manager.turns == []


def test_conversation_manager_add_and_retrieve_turn() -> None:
    """Verify adding turns records user prompt and response properly."""
    manager = ConversationManager()
    plan = DelegationPlan(reasoning="Test", mode=ExecutionMode.SINGLE, tasks=[])
    resp = OrchestratorResponse(
        content="Here are the notes on deep learning.",
        plan=plan,
        is_success=True,
    )

    turn = manager.add_turn("Find notes on deep learning", resp)

    assert isinstance(turn, ConversationTurn)
    assert turn.turn_index == 1
    assert turn.user_prompt == "Find notes on deep learning"
    assert turn.response_content == "Here are the notes on deep learning."
    assert turn.execution_mode == "single"
    assert manager.turn_count == 1

    summary = manager.get_context_summary()
    assert "Turn 1:" in summary
    assert "User: Find notes on deep learning" in summary
    assert "Assistant: Here are the notes on deep learning." in summary

    ctx_dict = manager.get_context_dict()
    assert ctx_dict["turn_count"] == 1
    assert "conversation_history" in ctx_dict


def test_conversation_manager_sliding_window_bound() -> None:
    """Verify only the last max_history_turns are retained in context summary."""
    manager = ConversationManager(max_history_turns=2, max_summary_chars=100)

    for i in range(1, 5):
        resp = OrchestratorResponse(content=f"Response {i}", is_success=True)
        manager.add_turn(f"Query {i}", resp)

    assert manager.turn_count == 4

    summary = manager.get_context_summary()
    # Turns 1 and 2 should have rolled out of the sliding window
    assert "Turn 1:" not in summary
    assert "Turn 2:" not in summary
    # Turns 3 and 4 should be retained
    assert "Turn 3:" in summary
    assert "User: Query 3" in summary
    assert "Turn 4:" in summary
    assert "User: Query 4" in summary


def test_conversation_manager_truncates_long_responses() -> None:
    """Verify assistant responses exceeding max_summary_chars are truncated with ellipsis."""
    manager = ConversationManager(max_history_turns=3, max_summary_chars=40)
    long_content = "This is a very long response that contains substantial academic details exceeding the limit."
    resp = OrchestratorResponse(content=long_content, is_success=True)

    manager.add_turn("Explain transformers", resp)
    summary = manager.get_context_summary()

    assert "..." in summary
    assert len(summary) < len(long_content) + 50


def test_conversation_manager_clear() -> None:
    """Verify clear() resets turn history completely."""
    manager = ConversationManager()
    resp = OrchestratorResponse(content="Response", is_success=True)
    manager.add_turn("Query", resp)
    assert manager.turn_count == 1

    manager.clear()
    assert manager.turn_count == 0
    assert manager.get_context_summary() == ""
    assert manager.get_context_dict() == {}
