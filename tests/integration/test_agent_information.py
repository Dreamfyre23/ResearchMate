"""Integration tests for Agent Information MCP tools and resources (Phase 4).

Validates:
- get_agent_info tool with UUID validation and not-found handling.
- list_agents tool with role and status filtering.
- get_agent_tasks tool with soft-delete filtering (DEC-028) and Attribution schema (DEC-027).
- agents://all resource.
- agents://active resource.
- agents://capabilities resource.
- Client session invocation of tools and resources over Streamable HTTP.
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
from database.models import Agent, Task
from server_mcp.config import MCPServerSettings
from server_mcp.server import create_app


def _find_free_port() -> int:
    """Find an available TCP port for ephemeral test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def seeded_agents_and_tasks() -> dict[str, Any]:
    """Seed sample agents and tasks for integration testing, cleaning up afterwards."""
    agent_1_id = uuid.uuid4()
    agent_2_id = uuid.uuid4()
    agent_3_id = uuid.uuid4()

    task_1_id = uuid.uuid4()
    task_2_id = uuid.uuid4()
    task_deleted_id = uuid.uuid4()

    with get_session() as session:
        # Create 3 distinct test agents
        agent_1 = Agent(
            agent_id=agent_1_id,
            name="Integration Test Research Agent",
            code="TEST-AGENT-001",
            role="research",
            description="Agent for testing research role.",
            model="gemini-3.5-flash-lite",
            provider="google",
            status="active",
            capabilities={
                "functional_capabilities": ["research", "summarization"],
                "mcp_tools": ["search_notes", "read_file"],
                "mcp_resources": ["notes://all"],
            },
        )
        agent_2 = Agent(
            agent_id=agent_2_id,
            name="Integration Test Task Agent",
            code="TEST-AGENT-002",
            role="task_management",
            description="Agent for testing task management.",
            model="gemini-3.5-flash-lite",
            provider="google",
            status="inactive",
            capabilities=["task_management", "create_task", "tasks://pending"],
        )
        agent_3 = Agent(
            agent_id=agent_3_id,
            name="Integration Test Orchestrator",
            code="TEST-AGENT-003",
            role="orchestrator",
            description="Agent for orchestrating workflows.",
            model="gemini-2.5-flash",
            provider="google",
            status="busy",
            capabilities=[],
        )
        session.add_all([agent_1, agent_2, agent_3])

        # Create tasks assigned to Agent 1
        # Task 1: in_progress, not deleted
        user_creator_id = uuid.uuid4()
        task_1 = Task(
            task_id=task_1_id,
            title="Active Task 1 for Agent 1",
            description="Description 1",
            status="in_progress",
            priority="high",
            assigned_agent_id=agent_1_id,
            created_by_user_id=user_creator_id,
            is_deleted=False,
        )
        # Task 2: pending, not deleted
        task_2 = Task(
            task_id=task_2_id,
            title="Pending Task 2 for Agent 1",
            description="Description 2",
            status="pending",
            priority="medium",
            assigned_agent_id=agent_1_id,
            created_by_agent_id=agent_3_id,
            is_deleted=False,
        )
        # Task 3: in_progress, soft-deleted (DEC-028)
        task_deleted = Task(
            task_id=task_deleted_id,
            title="Soft Deleted Task for Agent 1",
            description="Should not appear in task queries",
            status="in_progress",
            priority="low",
            assigned_agent_id=agent_1_id,
            created_by_user_id=user_creator_id,
            is_deleted=True,
        )
        session.add_all([task_1, task_2, task_deleted])
        session.commit()

    yield {
        "agent_1_id": agent_1_id,
        "agent_2_id": agent_2_id,
        "agent_3_id": agent_3_id,
        "task_1_id": task_1_id,
        "task_2_id": task_2_id,
        "task_deleted_id": task_deleted_id,
    }

    # Clean up test records
    with get_session() as session:
        session.execute(
            delete(Task).where(
                Task.task_id.in_([task_1_id, task_2_id, task_deleted_id])
            )
        )
        session.execute(
            delete(Agent).where(
                Agent.agent_id.in_([agent_1_id, agent_2_id, agent_3_id])
            )
        )
        session.commit()


@pytest.fixture
async def agent_mcp_server() -> AsyncGenerator[str, None]:
    """Start an ephemeral MCP server and yield its base URL."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="ResearchMate-AgentInfo-Test",
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


async def test_get_agent_info_tool(
    agent_mcp_server: str,
    seeded_agents_and_tasks: dict[str, Any],
) -> None:
    """Verify get_agent_info retrieves agent details, handles not found and invalid UUID."""
    mcp_url = f"{agent_mcp_server}/mcp"
    agent_1_id = seeded_agents_and_tasks["agent_1_id"]

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Valid agent lookup
        res = await session.call_tool("get_agent_info", {"agent_id": str(agent_1_id)})
        assert res is not None
        assert not res.is_error
        # FastMCP returns contents with text or structuredContent
        data = json.loads(res.content[0].text)
        assert data["agent_id"] == str(agent_1_id)
        assert data["name"] == "Integration Test Research Agent"
        assert data["code"] == "TEST-AGENT-001"
        assert data["role"] == "research"
        assert data["model"] == "gemini-3.5-flash-lite"
        assert data["provider"] == "google"
        assert data["status"] == "active"
        assert "capabilities" in data

        # 2. Non-existent UUID
        random_id = str(uuid.uuid4())
        res_not_found = await session.call_tool(
            "get_agent_info", {"agent_id": random_id}
        )
        data_not_found = json.loads(res_not_found.content[0].text)
        assert "error" in data_not_found
        assert f"'{random_id}' not found" in data_not_found["error"]

        # 3. Invalid UUID format
        res_invalid = await session.call_tool(
            "get_agent_info", {"agent_id": "not-a-valid-uuid"}
        )
        data_invalid = json.loads(res_invalid.content[0].text)
        assert "error" in data_invalid
        assert "Invalid UUID string format" in data_invalid["error"]


async def test_list_agents_tool_filtering(
    agent_mcp_server: str,
    seeded_agents_and_tasks: dict[str, Any],
) -> None:
    """Verify list_agents supports role and status filtering."""
    mcp_url = f"{agent_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. List all agents
        res_all = await session.call_tool("list_agents", {})
        agents_all = [json.loads(c.text) for c in res_all.content]
        assert isinstance(agents_all, list)
        assert len(agents_all) >= 3

        # 2. Filter by role
        res_research = await session.call_tool("list_agents", {"role": "research"})
        agents_research = [json.loads(c.text) for c in res_research.content]
        assert len(agents_research) >= 1
        assert all(a["role"] == "research" for a in agents_research)

        # 3. Filter by status
        res_inactive = await session.call_tool("list_agents", {"status": "inactive"})
        agents_inactive = [json.loads(c.text) for c in res_inactive.content]
        assert len(agents_inactive) >= 1
        assert all(a["status"] == "inactive" for a in agents_inactive)

        # 4. Filter by role + status matching none
        res_none = await session.call_tool(
            "list_agents", {"role": "task_management", "status": "active"}
        )
        agents_none = [json.loads(c.text) for c in res_none.content]
        assert agents_none == []


async def test_get_agent_tasks_tool_and_soft_delete(
    agent_mcp_server: str,
    seeded_agents_and_tasks: dict[str, Any],
) -> None:
    """Verify get_agent_tasks returns assigned tasks, excludes soft-deleted ones, and maps Attribution."""
    mcp_url = f"{agent_mcp_server}/mcp"
    agent_1_id = seeded_agents_and_tasks["agent_1_id"]
    agent_2_id = seeded_agents_and_tasks["agent_2_id"]
    task_deleted_id = seeded_agents_and_tasks["task_deleted_id"]

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Retrieve tasks for Agent 1 without status filter
        res = await session.call_tool("get_agent_tasks", {"agent_id": str(agent_1_id)})
        tasks = [json.loads(c.text) for c in res.content]
        assert isinstance(tasks, list)
        assert len(tasks) == 2  # Task 1 and Task 2, NOT Task 3 (soft-deleted)

        task_ids = {t["task_id"] for t in tasks}
        assert str(task_deleted_id) not in task_ids  # DEC-028 soft-delete verification

        # Verify DEC-027 Attribution object schema
        for t in tasks:
            assert t["assigned_to"] is not None
            assert t["assigned_to"]["type"] == "agent"
            assert t["assigned_to"]["id"] == str(agent_1_id)
            assert t["assigned_to"]["name"] == "Integration Test Research Agent"

        # 2. Filter by status="in_progress"
        res_in_progress = await session.call_tool(
            "get_agent_tasks",
            {"agent_id": str(agent_1_id), "status": "in_progress"},
        )
        tasks_in_progress = [json.loads(c.text) for c in res_in_progress.content]
        assert len(tasks_in_progress) == 1
        assert tasks_in_progress[0]["task_id"] == str(
            seeded_agents_and_tasks["task_1_id"]
        )

        # 3. Agent 2 has no tasks
        res_empty = await session.call_tool(
            "get_agent_tasks", {"agent_id": str(agent_2_id)}
        )
        tasks_empty = [json.loads(c.text) for c in res_empty.content]
        assert tasks_empty == []

        # 4. Non-existent agent
        random_id = str(uuid.uuid4())
        res_not_found = await session.call_tool(
            "get_agent_tasks", {"agent_id": random_id}
        )
        not_found_data = json.loads(res_not_found.content[0].text)
        assert "error" in not_found_data
        assert "not found" in not_found_data["error"]


async def test_agent_resources_via_client(
    agent_mcp_server: str,
    seeded_agents_and_tasks: dict[str, Any],
) -> None:
    """Verify agents://all, agents://active, and agents://capabilities resources."""
    mcp_url = f"{agent_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Read agents://all
        res_all = await session.read_resource("agents://all")
        assert len(res_all.contents) > 0
        data_all = json.loads(res_all.contents[0].text)
        assert "agents" in data_all
        assert len(data_all["agents"]) >= 3

        # 2. Read agents://active
        res_active = await session.read_resource("agents://active")
        assert len(res_active.contents) > 0
        data_active = json.loads(res_active.contents[0].text)
        assert "agents" in data_active
        assert len(data_active["agents"]) >= 1
        assert all(a["status"] == "active" for a in data_active["agents"])

        # 3. Read agents://capabilities
        res_caps = await session.read_resource("agents://capabilities")
        assert len(res_caps.contents) > 0
        data_caps = json.loads(res_caps.contents[0].text)
        assert "agents" in data_caps

        # Find Agent 1 in capabilities list
        agent_1_id_str = str(seeded_agents_and_tasks["agent_1_id"])
        agent_1_caps = next(
            (a for a in data_caps["agents"] if a["agent_id"] == agent_1_id_str),
            None,
        )
        assert agent_1_caps is not None
        assert agent_1_caps["functional_capabilities"] == ["research", "summarization"]
        assert agent_1_caps["mcp_tools"] == ["search_notes", "read_file"]
        assert agent_1_caps["mcp_resources"] == ["notes://all"]
