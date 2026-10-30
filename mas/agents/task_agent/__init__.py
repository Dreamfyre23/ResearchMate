"""Task Agent package for ResearchMate."""

from mas.agents.task_agent.agent import (
    TASK_AGENT_PERMITTED_TOOLS,
    TaskAgent,
)
from mas.agents.task_agent.prompts import TASK_AGENT_SYSTEM_PROMPT

__all__ = [
    "TASK_AGENT_PERMITTED_TOOLS",
    "TASK_AGENT_SYSTEM_PROMPT",
    "TaskAgent",
]
