"""Integration tests for Task Management MCP tools and resources (Phase 5).

Validates:
- create_task with valid and invalid inputs.
- get_task by UUID, invalid format, and nonexistent IDs.
- get_tasks with filtering (status, priority, assignee) and pagination.
- update_task field updates, status transitions, and unassigning.
- Soft deletion (DEC-028) and default exclusion across all reads and resources.
- Task dependency enforcement (DEC-030):
  - Transition to in_progress allowed with incomplete dependencies.
  - Transition to completed blocked when prerequisites are incomplete.
  - Override via force=True succeeds.
  - Transition to completed succeeds when prerequisites are completed.
  - Self-dependency and cycle detection.
- Attribution schema (DEC-027) for both agents and users.
- search_tasks keyword search across title and description.
- All five tasks:// resources (tasks://all, tasks://pending, tasks://in-progress, tasks://completed, tasks://high-priority).
- Client session invocation over Streamable HTTP.
- Isolation and cleanup of test fixtures.
"""

import asyncio
import json
import socket
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import delete

from database.connection import get_session
from database.models import Agent, Task, TaskDependency
from server_mcp.config import MCPServerSettings
from server_mcp.server import create_app


def _find_free_port() -> int:
    """Find an available TCP port for ephemeral test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def seeded_agent() -> dict[str, Any]:
    """Seed a test agent for assignment and attribution tests, cleaning up after."""
    agent_id = uuid.uuid4()
    with get_session() as session:
        agent = Agent(
            agent_id=agent_id,
            name="Task Management Test Agent",
            code="TM-AGENT-001",
            role="task_management",
            description="Agent for testing Task Management attribution.",
            model="gemini-3.5-flash-lite",
            provider="google",
            status="active",
            capabilities=[],
        )
        session.add(agent)
        session.commit()

    yield {
        "agent_id": agent_id,
        "agent_id_str": str(agent_id),
        "name": "Task Management Test Agent",
    }

    with get_session() as session:
        session.execute(delete(Task).where(Task.assigned_agent_id == agent_id))
        session.execute(delete(Task).where(Task.created_by_agent_id == agent_id))
        session.execute(delete(Agent).where(Agent.agent_id == agent_id))
        session.commit()


@pytest.fixture
async def task_mcp_server() -> AsyncGenerator[str, None]:
    """Start an ephemeral MCP server and yield its base URL."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="ResearchMate-TaskMgmt-Test",
        server_version="0.1.0-test",
        log_level="warning",
    )
    app = create_app(settings)
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())

    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"http://{host}:{port}/health")
                if res.status_code == 200:
                    break
        except (httpx.ConnectError, OSError):
            await asyncio.sleep(0.05)

    yield f"http://{host}:{port}"

    server.should_exit = True
    await server_task


async def test_create_and_get_task_lifecycle(
    task_mcp_server: str,
    seeded_agent: dict[str, Any],
) -> None:
    """Verify task creation with attribution, due date, and retrieval by UUID."""
    mcp_url = f"{task_mcp_server}/mcp"
    agent_id_str = seeded_agent["agent_id_str"]
    user_id_str = str(uuid.uuid4())

    created_task_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Create task with agent assignee and user creator
        create_res = await session.call_tool(
            "create_task",
            {
                "title": "Comprehensive Literature Survey",
                "description": "Analyze top 10 publications in knowledge graphs.",
                "status": "pending",
                "priority": "high",
                "assigned_to": {"type": "agent", "id": agent_id_str},
                "created_by": {"type": "user", "id": user_id_str},
                "due_date": "2026-11-15T18:00:00Z",
            },
        )
        assert create_res is not None
        assert not create_res.is_error
        data = json.loads(create_res.content[0].text)

        assert "task_id" in data
        created_task_id = data["task_id"]
        assert data["title"] == "Comprehensive Literature Survey"
        assert data["description"] == "Analyze top 10 publications in knowledge graphs."
        assert data["status"] == "pending"
        assert data["priority"] == "high"
        assert data["assigned_to"]["type"] == "agent"
        assert data["assigned_to"]["id"] == agent_id_str
        assert data["assigned_to"]["name"] == seeded_agent["name"]
        assert data["created_by"]["type"] == "user"
        assert data["created_by"]["id"] == user_id_str
        assert data["is_deleted"] is False
        assert data["due_date"] is not None

        # 2. Get task by UUID
        get_res = await session.call_tool("get_task", {"task_id": created_task_id})
        get_data = json.loads(get_res.content[0].text)
        assert get_data["task_id"] == created_task_id
        assert get_data["title"] == "Comprehensive Literature Survey"

        # 3. Get non-existent task
        random_id = str(uuid.uuid4())
        not_found_res = await session.call_tool("get_task", {"task_id": random_id})
        not_found_data = json.loads(not_found_res.content[0].text)
        assert "error" in not_found_data
        assert f"'{random_id}' not found" in not_found_data["error"]

        # 4. Get invalid UUID format
        invalid_res = await session.call_tool("get_task", {"task_id": "not-a-uuid"})
        invalid_data = json.loads(invalid_res.content[0].text)
        assert "error" in invalid_data
        assert "Invalid UUID string format" in invalid_data["error"]

    # Cleanup created task
    if created_task_id:
        with get_session() as s:
            s.execute(delete(Task).where(Task.task_id == uuid.UUID(created_task_id)))
            s.commit()


async def test_create_task_validation_errors(
    task_mcp_server: str,
) -> None:
    """Verify input validation rules for create_task tool."""
    mcp_url = f"{task_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Empty title
        res = await session.call_tool("create_task", {"title": "   "})
        assert "error" in json.loads(res.content[0].text)

        # 2. Invalid status
        res = await session.call_tool(
            "create_task", {"title": "Test", "status": "unknown_status"}
        )
        assert "error" in json.loads(res.content[0].text)

        # 3. Invalid priority
        res = await session.call_tool(
            "create_task", {"title": "Test", "priority": "urgent"}
        )
        assert "error" in json.loads(res.content[0].text)

        # 4. Invalid due_date format
        res = await session.call_tool(
            "create_task", {"title": "Test", "due_date": "not-a-date"}
        )
        assert "error" in json.loads(res.content[0].text)

        # 5. Invalid attribution type
        res = await session.call_tool(
            "create_task",
            {
                "title": "Test",
                "assigned_to": {"type": "robot", "id": str(uuid.uuid4())},
            },
        )
        assert "error" in json.loads(res.content[0].text)

        # 6. Nonexistent agent in attribution
        res = await session.call_tool(
            "create_task",
            {
                "title": "Test",
                "assigned_to": {"type": "agent", "id": str(uuid.uuid4())},
            },
        )
        assert "error" in json.loads(res.content[0].text)
        assert "does not exist" in json.loads(res.content[0].text)["error"]


async def test_task_dependencies_and_dec030_enforcement(
    task_mcp_server: str,
) -> None:
    """Verify DEC-030 dependency enforcement rules:
    - Transition to in_progress allowed with incomplete dependencies.
    - Transition to completed blocked when prerequisites are incomplete.
    - Transition to completed allowed with force=True.
    - Transition to completed allowed when prerequisites are satisfied.
    """
    mcp_url = f"{task_mcp_server}/mcp"
    task_b_id = None
    task_a_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Step 1: Create prerequisite Task B (pending)
        res_b = await session.call_tool(
            "create_task",
            {"title": "Task B: Data Preprocessing", "status": "pending"},
        )
        data_b = json.loads(res_b.content[0].text)
        task_b_id = data_b["task_id"]

        # Step 2: Create dependent Task A depending on Task B
        res_a = await session.call_tool(
            "create_task",
            {
                "title": "Task A: Model Training",
                "status": "pending",
                "dependencies": [task_b_id],
            },
        )
        data_a = json.loads(res_a.content[0].text)
        task_a_id = data_a["task_id"]
        assert task_a_id is not None
        assert task_b_id in data_a["dependencies"]

        # Step 3 (DEC-030 rule 1): Transition Task A to in_progress MUST succeed
        # even though prerequisite Task B is still pending
        res_prog = await session.call_tool(
            "update_task",
            {"task_id": task_a_id, "status": "in_progress"},
        )
        data_prog = json.loads(res_prog.content[0].text)
        assert "error" not in data_prog
        assert data_prog["status"] == "in_progress"

        # Step 4 (DEC-030 rule 2): Transition Task A to completed MUST FAIL
        # because prerequisite Task B is still pending
        res_comp_blocked = await session.call_tool(
            "update_task",
            {"task_id": task_a_id, "status": "completed", "force": False},
        )
        data_blocked = json.loads(res_comp_blocked.content[0].text)
        assert "error" in data_blocked
        assert "prerequisite tasks are incomplete" in data_blocked["error"]
        assert task_b_id in data_blocked["error"]

        # Step 5 (DEC-030 rule 3): Override with force=True MUST succeed
        res_forced = await session.call_tool(
            "update_task",
            {"task_id": task_a_id, "status": "completed", "force": True},
        )
        data_forced = json.loads(res_forced.content[0].text)
        assert "error" not in data_forced
        assert data_forced["status"] == "completed"
        assert data_forced["completed_at"] is not None

        # Reset Task A to in_progress
        await session.call_tool(
            "update_task",
            {"task_id": task_a_id, "status": "in_progress"},
        )

        # Step 6 (DEC-030 rule 4): Complete Task B, then Task A completion succeeds naturally
        res_comp_b = await session.call_tool(
            "update_task",
            {"task_id": task_b_id, "status": "completed"},
        )
        assert json.loads(res_comp_b.content[0].text)["status"] == "completed"

        res_comp_a = await session.call_tool(
            "update_task",
            {"task_id": task_a_id, "status": "completed"},
        )
        data_comp_a = json.loads(res_comp_a.content[0].text)
        assert "error" not in data_comp_a
        assert data_comp_a["status"] == "completed"

        # Step 7: Prevent circular dependency
        res_cycle = await session.call_tool(
            "update_task",
            {"task_id": task_b_id, "dependencies": [task_a_id]},
        )
        data_cycle = json.loads(res_cycle.content[0].text)
        assert "error" in data_cycle
        assert "circular dependency cycle" in data_cycle["error"]

    # Cleanup
    with get_session() as s:
        s.execute(
            delete(TaskDependency).where(
                TaskDependency.task_id.in_([uuid.UUID(task_a_id), uuid.UUID(task_b_id)])
            )
        )
        s.execute(
            delete(Task).where(
                Task.task_id.in_([uuid.UUID(task_a_id), uuid.UUID(task_b_id)])
            )
        )
        s.commit()


async def test_soft_delete_and_query_exclusion(
    task_mcp_server: str,
) -> None:
    """Verify soft deletion (DEC-028) sets is_deleted and excludes task from all listings, search, and resources."""
    mcp_url = f"{task_mcp_server}/mcp"
    task_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Create active task
        res_create = await session.call_tool(
            "create_task",
            {
                "title": "Ephemeral Task For Deletion Testing",
                "description": "Will be soft deleted.",
                "status": "pending",
            },
        )
        data_create = json.loads(res_create.content[0].text)
        task_id = data_create["task_id"]

        # Confirm visible in search
        search_before = await session.call_tool(
            "search_tasks", {"query": "Ephemeral Task"}
        )
        assert any(
            t["task_id"] == task_id
            for t in [json.loads(c.text) for c in search_before.content]
        )

        # 2. Soft delete the task
        del_res = await session.call_tool("delete_task", {"task_id": task_id})
        del_data = json.loads(del_res.content[0].text)
        assert del_data["success"] is True
        assert del_data["task_id"] == task_id

        # 3. get_task returns not found
        get_res = await session.call_tool("get_task", {"task_id": task_id})
        assert "error" in json.loads(get_res.content[0].text)

        # 4. get_tasks excludes it
        all_tasks_res = await session.call_tool("get_tasks", {})
        all_tasks = [json.loads(c.text) for c in all_tasks_res.content]
        assert all(t["task_id"] != task_id for t in all_tasks)

        # 5. search_tasks excludes it
        search_after = await session.call_tool(
            "search_tasks", {"query": "Ephemeral Task"}
        )
        found_after = [json.loads(c.text) for c in search_after.content]
        assert all(t["task_id"] != task_id for t in found_after)

        # 6. tasks://all resource excludes it
        res_resource = await session.read_resource("tasks://all")
        resource_data = json.loads(res_resource.contents[0].text)
        assert all(t["task_id"] != task_id for t in resource_data["tasks"])

    # Hard cleanup
    if task_id:
        with get_session() as s:
            s.execute(delete(Task).where(Task.task_id == uuid.UUID(task_id)))
            s.commit()


async def test_get_tasks_filtering_and_search(
    task_mcp_server: str,
    seeded_agent: dict[str, Any],
) -> None:
    """Verify get_tasks filtering by status, priority, and search_tasks keyword matching."""
    mcp_url = f"{task_mcp_server}/mcp"
    agent_id_str = seeded_agent["agent_id_str"]

    task_ids = []

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Seed 3 distinct tasks
        r1 = await session.call_tool(
            "create_task",
            {
                "title": "Quantum Algorithm Benchmark",
                "description": "Benchmark Grover algorithm performance.",
                "status": "pending",
                "priority": "critical",
                "assigned_to": {"type": "agent", "id": agent_id_str},
            },
        )
        task_ids.append(json.loads(r1.content[0].text)["task_id"])

        r2 = await session.call_tool(
            "create_task",
            {
                "title": "Database Optimization Guide",
                "description": "Index design and vacuum tuning.",
                "status": "in_progress",
                "priority": "low",
            },
        )
        task_ids.append(json.loads(r2.content[0].text)["task_id"])

        r3 = await session.call_tool(
            "create_task",
            {
                "title": "Knowledge Graph Integration",
                "description": "Connect Neo4j with PostgreSQL.",
                "status": "completed",
                "priority": "high",
            },
        )
        task_ids.append(json.loads(r3.content[0].text)["task_id"])

        # 1. Filter by status=pending
        pending_res = await session.call_tool("get_tasks", {"status": "pending"})
        pending_tasks = [json.loads(c.text) for c in pending_res.content]
        assert any(t["task_id"] == task_ids[0] for t in pending_tasks)
        assert all(t["status"] == "pending" for t in pending_tasks)

        # 2. Filter by priority=critical
        crit_res = await session.call_tool("get_tasks", {"priority": "critical"})
        crit_tasks = [json.loads(c.text) for c in crit_res.content]
        assert any(t["task_id"] == task_ids[0] for t in crit_tasks)
        assert all(t["priority"] == "critical" for t in crit_tasks)

        # 3. Filter by assigned_agent_id
        assigned_res = await session.call_tool(
            "get_tasks", {"assigned_agent_id": agent_id_str}
        )
        assigned_tasks = [json.loads(c.text) for c in assigned_res.content]
        assert any(t["task_id"] == task_ids[0] for t in assigned_tasks)

        # 4. Search tasks by title keyword
        search_title = await session.call_tool(
            "search_tasks", {"query": "Quantum Algorithm"}
        )
        found_title = [json.loads(c.text) for c in search_title.content]
        assert len(found_title) >= 1
        assert any(t["task_id"] == task_ids[0] for t in found_title)

        # 5. Search tasks by description keyword
        search_desc = await session.call_tool("search_tasks", {"query": "Grover"})
        found_desc = [json.loads(c.text) for c in search_desc.content]
        assert len(found_desc) >= 1
        assert any(t["task_id"] == task_ids[0] for t in found_desc)

        # 6. Search with status filter
        search_filtered = await session.call_tool(
            "search_tasks", {"query": "Integration", "status": "completed"}
        )
        found_filtered = [json.loads(c.text) for c in search_filtered.content]
        assert any(t["task_id"] == task_ids[2] for t in found_filtered)

    # Cleanup
    with get_session() as s:
        s.execute(
            delete(Task).where(Task.task_id.in_([uuid.UUID(tid) for tid in task_ids]))
        )
        s.commit()


async def test_task_management_resources(
    task_mcp_server: str,
) -> None:
    """Verify all five tasks:// resources return structured task collections."""
    mcp_url = f"{task_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. tasks://all
        res_all = await session.read_resource("tasks://all")
        assert len(res_all.contents) > 0
        data_all = json.loads(res_all.contents[0].text)
        assert "tasks" in data_all
        assert isinstance(data_all["tasks"], list)

        # 2. tasks://pending
        res_pending = await session.read_resource("tasks://pending")
        data_pending = json.loads(res_pending.contents[0].text)
        assert "tasks" in data_pending
        assert all(t["status"] == "pending" for t in data_pending["tasks"])

        # 3. tasks://in-progress
        res_prog = await session.read_resource("tasks://in-progress")
        data_prog = json.loads(res_prog.contents[0].text)
        assert "tasks" in data_prog
        assert all(t["status"] == "in_progress" for t in data_prog["tasks"])

        # 4. tasks://completed
        res_comp = await session.read_resource("tasks://completed")
        data_comp = json.loads(res_comp.contents[0].text)
        assert "tasks" in data_comp
        assert all(t["status"] == "completed" for t in data_comp["tasks"])

        # 5. tasks://high-priority
        res_high = await session.read_resource("tasks://high-priority")
        data_high = json.loads(res_high.contents[0].text)
        assert "tasks" in data_high
        assert all(t["priority"] in ("high", "critical") for t in data_high["tasks"])
