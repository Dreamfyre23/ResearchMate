"""Agent Information MCP tools for ResearchMate.

Implements the three tools specified in docs/MCP/Agent Information.md:
- get_agent_info
- list_agents
- get_agent_tasks
"""

import logging
import uuid
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.connection import get_session
from database.models import Agent, Task

logger = logging.getLogger(__name__)


def _serialize_agent(agent: Agent) -> dict[str, Any]:
    """Serialize an Agent ORM instance into a clean dictionary."""
    return {
        "agent_id": str(agent.agent_id),
        "name": agent.name,
        "code": agent.code,
        "role": agent.role,
        "description": agent.description,
        "model": agent.model,
        "provider": agent.provider,
        "status": agent.status,
        "capabilities": agent.capabilities,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "last_active_at": agent.last_active_at.isoformat()
        if agent.last_active_at
        else None,
    }


def register_agent_tools(server: MCPServer) -> None:
    """Register all 3 Agent Information MCP tools."""

    @server.tool(
        name="get_agent_info",
        description="Retrieve information about one registered agent using its UUID identifier.",
    )
    async def get_agent_info(agent_id: str) -> dict[str, Any]:
        """Fetch details for a single agent by UUID."""
        try:
            agent_uuid = uuid.UUID(agent_id)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{agent_id}'"}

        try:
            with get_session() as session:
                agent = session.get(Agent, agent_uuid)
                if not agent:
                    return {"error": f"Agent with id '{agent_id}' not found."}
                return _serialize_agent(agent)
        except SQLAlchemyError as exc:
            logger.error("Database error retrieving agent %s: %s", agent_id, exc)
            return {
                "error": "Internal database error occurred while fetching agent info."
            }

    @server.tool(
        name="list_agents",
        description="Retrieve registered agents, optionally filtered by role or status.",
    )
    async def list_agents(
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List registered agents matching optional role or status filters."""
        bounded_limit = max(1, min(limit, 500))
        try:
            with get_session() as session:
                query = select(Agent).order_by(Agent.name.asc()).limit(bounded_limit)
                if role:
                    query = query.where(Agent.role == role)
                if status:
                    query = query.where(Agent.status == status)

                agents = session.scalars(query).all()
                return [_serialize_agent(a) for a in agents]
        except SQLAlchemyError as exc:
            logger.error("Database error listing agents: %s", exc)
            return []

    @server.tool(
        name="get_agent_tasks",
        description="Retrieve tasks assigned to a particular agent by agent UUID.",
    )
    async def get_agent_tasks(
        agent_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Fetch active (non-deleted) tasks assigned to a specific agent."""
        try:
            agent_uuid = uuid.UUID(agent_id)
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{agent_id}'"}

        bounded_limit = max(1, min(limit, 500))
        try:
            with get_session() as session:
                agent = session.get(Agent, agent_uuid)
                if not agent:
                    return {"error": f"Agent with id '{agent_id}' not found."}

                query = (
                    select(Task)
                    .where(Task.assigned_agent_id == agent_uuid)
                    .where(Task.is_deleted.is_(False))
                    .order_by(Task.created_at.desc())
                    .limit(bounded_limit)
                )
                if status:
                    query = query.where(Task.status == status)

                tasks = session.scalars(query).all()
                results = []
                for t in tasks:
                    creator_info = None
                    if t.created_by_agent_id:
                        creator_info = {
                            "type": "agent",
                            "id": str(t.created_by_agent_id),
                            "name": t.created_by_agent.name
                            if t.created_by_agent
                            else None,
                        }
                    results.append(
                        {
                            "task_id": str(t.task_id),
                            "title": t.title,
                            "description": t.description,
                            "status": t.status,
                            "priority": t.priority,
                            "assigned_to": {
                                "type": "agent",
                                "id": str(agent.agent_id),
                                "name": agent.name,
                            },
                            "created_by": creator_info,
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "created_at": t.created_at.isoformat()
                            if t.created_at
                            else None,
                            "updated_at": t.updated_at.isoformat()
                            if t.updated_at
                            else None,
                            "completed_at": t.completed_at.isoformat()
                            if t.completed_at
                            else None,
                        }
                    )
                return results
        except SQLAlchemyError as exc:
            logger.error(
                "Database error fetching tasks for agent %s: %s", agent_id, exc
            )
            return {
                "error": "Internal database error occurred while fetching agent tasks."
            }
