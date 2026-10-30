"""Agent Information MCP resources for ResearchMate.

Implements the three resources specified in docs/MCP/Agent Information.md:
- agents://all
- agents://active
- agents://capabilities
"""

import json
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.connection import get_session
from database.models import Agent
from server_mcp.tools.agent_information import _serialize_agent

logger = logging.getLogger(__name__)


def _format_agent_capabilities(agent: Agent) -> dict[str, Any]:
    """Extract and format structured capability records for an agent."""
    raw = agent.capabilities
    functional: list[str] = []
    tools: list[str] = []
    resources: list[str] = []

    if isinstance(raw, dict):
        functional = list(raw.get("functional_capabilities", []))
        tools = list(raw.get("mcp_tools", []))
        resources = list(raw.get("mcp_resources", []))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                if "://" in item:
                    resources.append(item)
                elif "_" in item or "-" in item:
                    tools.append(item)
                else:
                    functional.append(item)
            elif isinstance(item, dict):
                if "tool" in item:
                    tools.append(str(item["tool"]))
                elif "resource" in item:
                    resources.append(str(item["resource"]))
                elif "capability" in item:
                    functional.append(str(item["capability"]))

    return {
        "agent_id": str(agent.agent_id),
        "name": agent.name,
        "code": agent.code,
        "functional_capabilities": functional,
        "mcp_tools": tools,
        "mcp_resources": resources,
    }


def get_all_agents() -> list[dict[str, Any]]:
    """Fetch and serialize all registered agents."""
    try:
        with get_session() as session:
            agents = session.scalars(select(Agent).order_by(Agent.name.asc())).all()
            return [_serialize_agent(a) for a in agents]
    except SQLAlchemyError as exc:
        logger.error("Failed to query all agents for resource: %s", exc)
        return []


def get_active_agents() -> list[dict[str, Any]]:
    """Fetch and serialize registered agents with active status."""
    try:
        with get_session() as session:
            agents = session.scalars(
                select(Agent).where(Agent.status == "active").order_by(Agent.name.asc())
            ).all()
            return [_serialize_agent(a) for a in agents]
    except SQLAlchemyError as exc:
        logger.error("Failed to query active agents for resource: %s", exc)
        return []


def get_agent_capabilities() -> list[dict[str, Any]]:
    """Fetch and format capabilities for all registered agents."""
    try:
        with get_session() as session:
            agents = session.scalars(select(Agent).order_by(Agent.name.asc())).all()
            return [_format_agent_capabilities(a) for a in agents]
    except SQLAlchemyError as exc:
        logger.error("Failed to query agent capabilities for resource: %s", exc)
        return []


def register_agent_resources(server: MCPServer) -> None:
    """Register all 3 Agent Information MCP resources."""

    @server.resource(
        "agents://all",
        name="All Registered Agents",
        description="Comprehensive information about all registered AI agents.",
        mime_type="application/json",
    )
    def resource_agents_all() -> str:
        return json.dumps({"agents": get_all_agents()}, indent=2)

    @server.resource(
        "agents://active",
        name="Active Registered Agents",
        description="Information about registered agents whose reported status is active.",
        mime_type="application/json",
    )
    def resource_agents_active() -> str:
        return json.dumps({"agents": get_active_agents()}, indent=2)

    @server.resource(
        "agents://capabilities",
        name="Agent Capabilities",
        description="Registered agent capabilities, including functional capabilities and MCP tools/resources.",
        mime_type="application/json",
    )
    def resource_agents_capabilities() -> str:
        return json.dumps({"agents": get_agent_capabilities()}, indent=2)
