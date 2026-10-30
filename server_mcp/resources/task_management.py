"""Task Management MCP resources for ResearchMate.

Implements the five resources specified in docs/MCP/Task Management.md:
- tasks://all
- tasks://pending
- tasks://in-progress
- tasks://completed
- tasks://high-priority

Complies with DEC-028 (soft-deletion exclusion) and DEC-026 (UUID serialization).
"""

import json
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import Task
from server_mcp.tools.task_management import _serialize_task

logger = logging.getLogger(__name__)


def _query_tasks_with_filter(where_clause: Any | None = None) -> list[dict[str, Any]]:
    """Helper to query non-deleted tasks with eager loading and serialize them."""
    try:
        with get_session() as session:
            query = (
                select(Task)
                .options(
                    joinedload(Task.assigned_agent),
                    joinedload(Task.created_by_agent),
                    selectinload(Task.dependencies),
                )
                .where(Task.is_deleted.is_(False))
                .order_by(Task.created_at.desc())
            )
            if where_clause is not None:
                query = query.where(where_clause)

            tasks = session.scalars(query).all()
            return [_serialize_task(t) for t in tasks]
    except SQLAlchemyError as exc:
        logger.error("Failed to query tasks for resource: %s", exc)
        return []


def register_task_resources(server: MCPServer) -> None:
    """Register all 5 Task Management MCP resources."""

    @server.resource(
        "tasks://all",
        name="All Tasks",
        description="Collection of all active (non-deleted) tasks.",
        mime_type="application/json",
    )
    def resource_tasks_all() -> str:
        return json.dumps({"tasks": _query_tasks_with_filter()}, indent=2)

    @server.resource(
        "tasks://pending",
        name="Pending Tasks",
        description="Collection of tasks awaiting execution (status: pending).",
        mime_type="application/json",
    )
    def resource_tasks_pending() -> str:
        return json.dumps(
            {"tasks": _query_tasks_with_filter(Task.status == "pending")},
            indent=2,
        )

    @server.resource(
        "tasks://in-progress",
        name="In-Progress Tasks",
        description="Collection of tasks currently underway (status: in_progress).",
        mime_type="application/json",
    )
    def resource_tasks_in_progress() -> str:
        return json.dumps(
            {"tasks": _query_tasks_with_filter(Task.status == "in_progress")},
            indent=2,
        )

    @server.resource(
        "tasks://completed",
        name="Completed Tasks",
        description="Collection of successfully finished tasks (status: completed).",
        mime_type="application/json",
    )
    def resource_tasks_completed() -> str:
        return json.dumps(
            {"tasks": _query_tasks_with_filter(Task.status == "completed")},
            indent=2,
        )

    @server.resource(
        "tasks://high-priority",
        name="High-Priority Tasks",
        description="Collection of urgent tasks with high or critical priority.",
        mime_type="application/json",
    )
    def resource_tasks_high_priority() -> str:
        return json.dumps(
            {
                "tasks": _query_tasks_with_filter(
                    Task.priority.in_(["high", "critical"])
                )
            },
            indent=2,
        )
