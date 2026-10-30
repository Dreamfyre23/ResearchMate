"""Multi-turn conversation management for ResearchMate (Phase 11).

Maintains bounded conversation history to preserve conversational context across
multiple user turns without causing prompt bloat or memory exhaustion on 8 GB RAM systems.
"""

import time
from dataclasses import dataclass
from typing import Any

from mas.orchestrator.models import OrchestratorResponse


@dataclass
class ConversationTurn:
    """Record of a single completed conversation turn."""

    turn_index: int
    user_prompt: str
    response_content: str
    execution_mode: str
    timestamp: float


class ConversationManager:
    """Manages multi-turn conversation history with bounded sliding-window retention."""

    def __init__(
        self,
        max_history_turns: int = 3,
        max_summary_chars: int = 250,
    ) -> None:
        """Initialize the ConversationManager.

        Args:
            max_history_turns: Maximum number of recent turns to preserve in context.
            max_summary_chars: Maximum characters retained from each assistant response.
        """
        self.max_history_turns = max_history_turns
        self.max_summary_chars = max_summary_chars
        self._turns: list[ConversationTurn] = []

    def add_turn(
        self,
        user_prompt: str,
        response: OrchestratorResponse,
    ) -> ConversationTurn:
        """Record a completed conversation turn.

        Args:
            user_prompt: The user's input prompt for this turn.
            response: The orchestrator's synthesized response.

        Returns:
            The newly created ConversationTurn record.
        """
        mode_val = (
            response.plan.mode.value
            if response.plan and response.plan.mode
            else "unknown"
        )
        turn = ConversationTurn(
            turn_index=len(self._turns) + 1,
            user_prompt=user_prompt.strip(),
            response_content=response.content.strip(),
            execution_mode=mode_val,
            timestamp=time.time(),
        )
        self._turns.append(turn)
        return turn

    def get_context_summary(self) -> str:
        """Return a bounded summary of recent conversation turns for context preservation.

        Returns an empty string if there are no prior turns.
        """
        if not self._turns:
            return ""

        recent = self._turns[-self.max_history_turns :]
        lines: list[str] = []
        for t in recent:
            # Bound assistant response to prevent token explosion
            resp = t.response_content
            if len(resp) > self.max_summary_chars:
                resp = resp[: self.max_summary_chars].rstrip() + "..."
            lines.append(f"Turn {t.turn_index}:")
            lines.append(f"  User: {t.user_prompt}")
            lines.append(f"  Assistant: {resp}")
        return "\n".join(lines)

    def get_context_dict(self) -> dict[str, Any]:
        """Return context dictionary suitable for passing to OrchestratorRequest."""
        summary = self.get_context_summary()
        if not summary:
            return {}
        return {
            "conversation_history": summary,
            "turn_count": len(self._turns),
        }

    def clear(self) -> None:
        """Clear all conversation history (e.g. for /reset command)."""
        self._turns.clear()

    @property
    def turn_count(self) -> int:
        """Return total number of recorded conversation turns."""
        return len(self._turns)

    @property
    def turns(self) -> list[ConversationTurn]:
        """Return read-only copy of conversation turns."""
        return list(self._turns)
