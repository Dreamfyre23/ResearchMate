"""Task Management MCP tools for ResearchMate.

Implements the six tools specified in docs/MCP/Task Management.md:
- create_task
- get_task
- get_tasks
- update_task
- delete_task
- search_tasks

Complies with:
- DEC-026: UUID standardization
- DEC-027: Unified Attribution object
- DEC-028: Soft deletion policy
- DEC-030: Task dependency enforcement rules
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import Agent, Task, TaskDependency

logger = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def _parse_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    cleaned = dt_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_attribution(
    data: dict[str, Any] | None,
    session: Any,
    field_name: str,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Parse and validate canonical Attribution object (DEC-027).

    Returns:
        (agent_id, user_id, error_message)
    """
    if data is None:
        return None, None, None

    if not isinstance(data, dict):
        return None, None, f"'{field_name}' must be an Attribution dictionary."

    attr_type = data.get("type")
    attr_id_str = data.get("id")

    if not attr_type or attr_type not in ("agent", "user"):
        return None, None, f"'{field_name}.type' must be 'agent' or 'user'."

    if not attr_id_str:
        return None, None, f"'{field_name}.id' is required."

    try:
        attr_uuid = uuid.UUID(str(attr_id_str))
    except (ValueError, TypeError, AttributeError):
        return (
            None,
            None,
            f"Invalid UUID format for '{field_name}.id': '{attr_id_str}'.",
        )

    if attr_type == "agent":
        agent = session.get(Agent, attr_uuid)
        if not agent:
            return (
                None,
                None,
                f"Referenced agent '{attr_uuid}' in '{field_name}' does not exist.",
            )
        return attr_uuid, None, None
    else:  # user
        return None, attr_uuid, None


def _serialize_task(task: Task) -> dict[str, Any]:
    """Serialize a Task ORM instance into the standard Task representation."""
    assigned_to = None
    if task.assigned_agent_id:
        assigned_to = {
            "type": "agent",
            "id": str(task.assigned_agent_id),
            "name": task.assigned_agent.name if task.assigned_agent else None,
        }
    elif task.assigned_user_id:
        assigned_to = {
            "type": "user",
            "id": str(task.assigned_user_id),
            "name": None,
        }

    created_by = None
    if task.created_by_agent_id:
        created_by = {
            "type": "agent",
            "id": str(task.created_by_agent_id),
            "name": task.created_by_agent.name if task.created_by_agent else None,
        }
    elif task.created_by_user_id:
        created_by = {
            "type": "user",
            "id": str(task.created_by_user_id),
            "name": None,
        }

    dep_ids = (
        [str(d.depends_on_task_id) for d in task.dependencies]
        if task.dependencies
        else []
    )

    return {
        "task_id": str(task.task_id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "assigned_to": assigned_to,
        "created_by": created_by,
        "dependencies": dep_ids,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "is_deleted": task.is_deleted,
    }


def _would_create_cycle(
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    session: Any,
) -> bool:
    """Check if adding dependency depends_on_id to task_id would create a cycle."""
    visited = set()
    queue = [depends_on_id]
    while queue:
        curr = queue.pop(0)
        if curr == task_id:
            return True
        if curr in visited:
            continue
        visited.add(curr)
        prereqs = session.scalars(
            select(TaskDependency.depends_on_task_id).where(
                TaskDependency.task_id == curr
            )
        ).all()
        for p in prereqs:
            if p not in visited:
                queue.append(p)
    return False


def _check_incomplete_dependencies(task: Task, session: Any) -> list[str]:
    """Find any prerequisite tasks that are incomplete (not status='completed')."""
    incomplete: list[str] = []
    for dep in task.dependencies:
        prereq = session.get(Task, dep.depends_on_task_id)
        if not prereq or prereq.is_deleted or prereq.status != "completed":
            incomplete.append(str(dep.depends_on_task_id))
    return incomplete


def register_task_tools(server: MCPServer) -> None:
    """Register all 6 Task Management MCP tools."""

    @server.tool(
        name="create_task",
        description="Create a new task with optional priority, status, assignee, deadline, and dependencies.",
    )
    async def create_task(
        title: str,
        description: str | None = None,
        status: str = "pending",
        priority: str = "medium",
        assigned_to: dict[str, Any] | None = None,
        created_by: dict[str, Any] | None = None,
        due_date: str | None = None,
        dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new task in PostgreSQL."""
        if not title or not title.strip():
            return {"error": "Task title cannot be empty."}

        status_lower = status.lower().strip()
        if status_lower not in VALID_STATUSES:
            return {
                "error": f"Invalid status: '{status}'. Valid statuses: {sorted(VALID_STATUSES)}."
            }

        priority_lower = priority.lower().strip()
        if priority_lower not in VALID_PRIORITIES:
            return {
                "error": f"Invalid priority: '{priority}'. Valid priorities: {sorted(VALID_PRIORITIES)}."
            }

        parsed_due_date = None
        if due_date:
            try:
                parsed_due_date = _parse_datetime(due_date)
            except (ValueError, TypeError):
                return {
                    "error": f"Invalid due_date format: '{due_date}'. Expected ISO 8601 string."
                }

        try:
            with get_session() as session:
                # Parse and validate Attribution
                assigned_agent_id, assigned_user_id, err = _parse_attribution(
                    assigned_to, session, "assigned_to"
                )
                if err:
                    return {"error": err}

                created_agent_id, created_user_id, err = _parse_attribution(
                    created_by, session, "created_by"
                )
                if err:
                    return {"error": err}

                new_task_id = uuid.uuid4()
                now_utc = datetime.now(UTC)

                task = Task(
                    task_id=new_task_id,
                    title=title.strip(),
                    description=description.strip() if description else None,
                    status=status_lower,
                    priority=priority_lower,
                    assigned_agent_id=assigned_agent_id,
                    assigned_user_id=assigned_user_id,
                    created_by_agent_id=created_agent_id,
                    created_by_user_id=created_user_id,
                    due_date=parsed_due_date,
                    is_deleted=False,
                    completed_at=now_utc if status_lower == "completed" else None,
                )
                session.add(task)
                session.flush()

                # Process dependencies
                if dependencies:
                    dep_rows = []
                    for dep_str in dependencies:
                        try:
                            dep_uuid = uuid.UUID(dep_str.strip())
                        except (ValueError, TypeError, AttributeError):
                            return {
                                "error": f"Invalid dependency task UUID: '{dep_str}'."
                            }

                        if dep_uuid == new_task_id:
                            return {"error": "A task cannot depend on itself."}

                        prereq = session.get(Task, dep_uuid)
                        if not prereq or prereq.is_deleted:
                            return {
                                "error": f"Prerequisite task '{dep_uuid}' does not exist or has been deleted."
                            }

                        dep_rows.append(
                            TaskDependency(
                                task_id=new_task_id, depends_on_task_id=dep_uuid
                            )
                        )

                    session.add_all(dep_rows)
                    session.flush()

                # If created directly with status='completed', verify dependencies
                if status_lower == "completed":
                    session.refresh(task, ["dependencies"])
                    incomplete = _check_incomplete_dependencies(task, session)
                    if incomplete:
                        return {
                            "error": f"Cannot create task directly as 'completed': prerequisite tasks are incomplete: {incomplete}."
                        }

                session.commit()

                # Re-query with eager loading to serialize cleanly
                saved_task = session.scalar(
                    select(Task)
                    .options(
                        joinedload(Task.assigned_agent),
                        joinedload(Task.created_by_agent),
                        selectinload(Task.dependencies),
                    )
                    .where(Task.task_id == new_task_id)
                )
                return _serialize_task(saved_task)

        except SQLAlchemyError as exc:
            logger.error("Database error creating task: %s", exc)
            return {"error": "Internal database error occurred while creating task."}

    @server.tool(
        name="get_task",
        description="Retrieve a single task by its standard UUID identifier.",
    )
    async def get_task(task_id: str) -> dict[str, Any]:
        """Fetch task details by task UUID."""
        try:
            task_uuid = uuid.UUID(task_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{task_id}'."}

        try:
            with get_session() as session:
                task = session.scalar(
                    select(Task)
                    .options(
                        joinedload(Task.assigned_agent),
                        joinedload(Task.created_by_agent),
                        selectinload(Task.dependencies),
                    )
                    .where(Task.task_id == task_uuid, Task.is_deleted.is_(False))
                )
                if not task:
                    return {"error": f"Task with id '{task_id}' not found."}
                return _serialize_task(task)
        except SQLAlchemyError as exc:
            logger.error("Database error retrieving task %s: %s", task_id, exc)
            return {"error": "Internal database error occurred while fetching task."}

    @server.tool(
        name="get_tasks",
        description="Retrieve tasks with optional filtering by status, priority, assignee, and pagination.",
    )
    async def get_tasks(
        status: str | None = None,
        priority: str | None = None,
        assigned_agent_id: str | None = None,
        assigned_user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """List tasks matching optional filters, excluding soft-deleted tasks."""
        safe_limit = limit if limit is not None else 100
        safe_offset = offset if offset is not None else 0
        bounded_limit = max(1, min(safe_limit, 500))
        bounded_offset = max(0, safe_offset)

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
                    .offset(bounded_offset)
                    .limit(bounded_limit)
                )

                if status:
                    status_lower = status.lower().strip()
                    if status_lower not in VALID_STATUSES:
                        return {"error": f"Invalid status filter: '{status}'."}
                    query = query.where(Task.status == status_lower)

                if priority:
                    priority_lower = priority.lower().strip()
                    if priority_lower not in VALID_PRIORITIES:
                        return {"error": f"Invalid priority filter: '{priority}'."}
                    query = query.where(Task.priority == priority_lower)

                if assigned_agent_id:
                    try:
                        agent_uuid = uuid.UUID(assigned_agent_id.strip())
                        query = query.where(Task.assigned_agent_id == agent_uuid)
                    except (ValueError, TypeError):
                        return {
                            "error": f"Invalid assigned_agent_id UUID: '{assigned_agent_id}'."
                        }

                if assigned_user_id:
                    try:
                        user_uuid = uuid.UUID(assigned_user_id.strip())
                        query = query.where(Task.assigned_user_id == user_uuid)
                    except (ValueError, TypeError):
                        return {
                            "error": f"Invalid assigned_user_id UUID: '{assigned_user_id}'."
                        }

                tasks = session.scalars(query).all()
                return [_serialize_task(t) for t in tasks]

        except SQLAlchemyError as exc:
            logger.error("Database error listing tasks: %s", exc)
            return {"error": "Internal database error occurred while querying tasks."}

    @server.tool(
        name="update_task",
        description="Update an existing task's fields, status, assignee, or dependencies.",
    )
    async def update_task(
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: dict[str, Any] | None = None,
        due_date: str | None = None,
        dependencies: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Update fields on an existing task with DEC-030 dependency enforcement."""
        try:
            task_uuid = uuid.UUID(task_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{task_id}'."}

        try:
            with get_session() as session:
                task = session.scalar(
                    select(Task)
                    .options(
                        joinedload(Task.assigned_agent),
                        joinedload(Task.created_by_agent),
                        selectinload(Task.dependencies),
                    )
                    .where(Task.task_id == task_uuid, Task.is_deleted.is_(False))
                )
                if not task:
                    return {"error": f"Task with id '{task_id}' not found."}

                if title is not None:
                    if not title.strip():
                        return {"error": "Task title cannot be empty."}
                    task.title = title.strip()

                if description is not None:
                    task.description = description.strip() if description else None

                if priority is not None:
                    p_lower = priority.lower().strip()
                    if p_lower not in VALID_PRIORITIES:
                        return {
                            "error": f"Invalid priority: '{priority}'. Valid priorities: {sorted(VALID_PRIORITIES)}."
                        }
                    task.priority = p_lower

                if due_date is not None:
                    if due_date == "":
                        task.due_date = None
                    else:
                        try:
                            task.due_date = _parse_datetime(due_date)
                        except (ValueError, TypeError):
                            return {"error": f"Invalid due_date format: '{due_date}'."}

                if assigned_to is not None:
                    if assigned_to == {}:
                        # Unassign task
                        task.assigned_agent_id = None
                        task.assigned_user_id = None
                    else:
                        a_agent_id, a_user_id, err = _parse_attribution(
                            assigned_to, session, "assigned_to"
                        )
                        if err:
                            return {"error": err}
                        task.assigned_agent_id = a_agent_id
                        task.assigned_user_id = a_user_id

                # Update dependencies if supplied
                if dependencies is not None:
                    # Clear existing dependencies
                    task.dependencies.clear()
                    session.flush()

                    for dep_str in dependencies:
                        try:
                            dep_uuid = uuid.UUID(dep_str.strip())
                        except (ValueError, TypeError, AttributeError):
                            return {"error": f"Invalid dependency UUID: '{dep_str}'."}

                        if dep_uuid == task_uuid:
                            return {"error": "A task cannot depend on itself."}

                        prereq = session.get(Task, dep_uuid)
                        if not prereq or prereq.is_deleted:
                            return {
                                "error": f"Prerequisite task '{dep_uuid}' does not exist or has been deleted."
                            }

                        if _would_create_cycle(task_uuid, dep_uuid, session):
                            return {
                                "error": f"Adding dependency on task '{dep_uuid}' would create a circular dependency cycle."
                            }

                        task.dependencies.append(
                            TaskDependency(
                                task_id=task_uuid, depends_on_task_id=dep_uuid
                            )
                        )
                    session.flush()

                # Status transition and dependency enforcement (DEC-030)
                if status is not None:
                    s_lower = status.lower().strip()
                    if s_lower not in VALID_STATUSES:
                        return {
                            "error": f"Invalid status: '{status}'. Valid statuses: {sorted(VALID_STATUSES)}."
                        }

                    # DEC-030: Transition to completed requires all dependencies to be complete unless force=True
                    if s_lower == "completed":
                        incomplete = _check_incomplete_dependencies(task, session)
                        if incomplete and not force:
                            return {
                                "error": (
                                    f"Cannot complete task '{task_id}': prerequisite tasks are incomplete: {incomplete}. "
                                    f"Supply force=True to override."
                                )
                            }
                        task.status = "completed"
                        task.completed_at = datetime.now(UTC)
                    else:
                        task.status = s_lower
                        task.completed_at = None

                task.updated_at = datetime.now(UTC)
                session.commit()

                # Refresh and serialize
                refreshed = session.scalar(
                    select(Task)
                    .options(
                        joinedload(Task.assigned_agent),
                        joinedload(Task.created_by_agent),
                        selectinload(Task.dependencies),
                    )
                    .where(Task.task_id == task_uuid)
                )
                return _serialize_task(refreshed)

        except SQLAlchemyError as exc:
            logger.error("Database error updating task %s: %s", task_id, exc)
            return {"error": "Internal database error occurred while updating task."}

    @server.tool(
        name="delete_task",
        description="Soft delete a task by UUID, preserving dependencies and historical records (DEC-028).",
    )
    async def delete_task(task_id: str) -> dict[str, Any]:
        """Soft delete a task by marking is_deleted=True and setting deleted_at."""
        try:
            task_uuid = uuid.UUID(task_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{task_id}'."}

        try:
            with get_session() as session:
                task = session.scalar(
                    select(Task).where(
                        Task.task_id == task_uuid, Task.is_deleted.is_(False)
                    )
                )
                if not task:
                    return {"error": f"Task with id '{task_id}' not found."}

                task.is_deleted = True
                task.deleted_at = datetime.now(UTC)
                task.updated_at = datetime.now(UTC)
                session.commit()

                return {
                    "success": True,
                    "message": f"Task '{task_id}' soft-deleted successfully.",
                    "task_id": task_id,
                }
        except SQLAlchemyError as exc:
            logger.error("Database error deleting task %s: %s", task_id, exc)
            return {"error": "Internal database error occurred while deleting task."}

    @server.tool(
        name="search_tasks",
        description="Search non-deleted tasks by keyword matching title or description.",
    )
    async def search_tasks(
        query: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Search tasks using substring matching across title and description."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return {"error": "Search query cannot be empty."}

        bounded_limit = max(1, min(limit, 200))

        try:
            with get_session() as session:
                search_filter = or_(
                    Task.title.ilike(f"%{cleaned_query}%"),
                    Task.description.ilike(f"%{cleaned_query}%"),
                )
                stmt = (
                    select(Task)
                    .options(
                        joinedload(Task.assigned_agent),
                        joinedload(Task.created_by_agent),
                        selectinload(Task.dependencies),
                    )
                    .where(Task.is_deleted.is_(False), search_filter)
                    .order_by(Task.created_at.desc())
                    .limit(bounded_limit)
                )

                if status:
                    s_lower = status.lower().strip()
                    if s_lower not in VALID_STATUSES:
                        return {"error": f"Invalid status filter: '{status}'."}
                    stmt = stmt.where(Task.status == s_lower)

                tasks = session.scalars(stmt).all()
                return [_serialize_task(t) for t in tasks]

        except SQLAlchemyError as exc:
            logger.error("Database error searching tasks: %s", exc)
            return {"error": "Internal database error occurred while searching tasks."}
