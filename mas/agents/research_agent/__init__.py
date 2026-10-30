"""Research Agent package for ResearchMate."""

from mas.agents.research_agent.agent import (
    RESEARCH_AGENT_PERMITTED_TOOLS,
    ResearchAgent,
)
from mas.agents.research_agent.prompts import RESEARCH_AGENT_SYSTEM_PROMPT

__all__ = [
    "RESEARCH_AGENT_PERMITTED_TOOLS",
    "RESEARCH_AGENT_SYSTEM_PROMPT",
    "ResearchAgent",
]
