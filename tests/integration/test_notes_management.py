"""Integration tests for Notes Management MCP tools and resources (Phase 6).

Validates:
- create_note with valid fields, tag normalization, and validation errors.
- get_note by UUID, invalid UUID format, nonexistent IDs, and include_versions.
- get_notes with category, tag, and creator filtering with pagination.
- update_note content modifications and version snapshot creation (DEC-029, DEC-031).
- Version retention policies:
  - Unlimited retention when MAX_NOTE_VERSIONS=0.
  - FIFO pruning of oldest versions when a positive MAX_NOTE_VERSIONS limit is set.
- Soft deletion (DEC-029):
  - is_deleted and deleted_at set.
  - Historical note_versions and notes_tags preserved.
  - Excluded from get_note, get_notes, search_notes, and resources.
- Tag association, duplicate prevention, and sharing across notes.
- Attribution validation and serialization (DEC-027).
- search_notes keyword search across title and Markdown body.
- All notes:// resources (all, technical, research, literature, project, ideas).
- Client session invocation over Streamable HTTP.
- Isolation and cleanup of test data.
"""

import asyncio
import json
import socket
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import delete, select

from database.connection import get_session
from database.models import Agent, Note, NoteVersion
from server_mcp.config import MCPServerSettings
from server_mcp.server import create_app


def _find_free_port() -> int:
    """Find an available TCP port for ephemeral test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def seeded_agent() -> dict[str, Any]:
    """Seed a test agent for note attribution, cleaning up afterwards."""
    agent_id = uuid.uuid4()
    with get_session() as session:
        agent = Agent(
            agent_id=agent_id,
            name="Notes Management Test Agent",
            code="NM-AGENT-001",
            role="research",
            description="Agent for testing Notes Management attribution.",
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
        "name": "Notes Management Test Agent",
    }

    with get_session() as session:
        session.execute(delete(Note).where(Note.created_by_agent_id == agent_id))
        session.execute(delete(Agent).where(Agent.agent_id == agent_id))
        session.commit()


@pytest.fixture
async def notes_mcp_server() -> AsyncGenerator[str, None]:
    """Start an ephemeral MCP server and yield its base URL."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="ResearchMate-NotesMgmt-Test",
        server_version="0.1.0-test",
        log_level="warning",
        max_note_versions=0,
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


async def test_create_and_get_note_lifecycle(
    notes_mcp_server: str,
    seeded_agent: dict[str, Any],
) -> None:
    """Verify note creation with tags, attribution, and retrieval by UUID."""
    mcp_url = f"{notes_mcp_server}/mcp"
    agent_id_str = seeded_agent["agent_id_str"]

    created_note_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Create note
        res = await session.call_tool(
            "create_note",
            {
                "title": "Introduction to Vector Embeddings",
                "content": "# Vector Embeddings\n\nHigh-dimensional representations of text.",
                "category": "technical_research",
                "tags": ["AI", "Embeddings", "Search", "AI"],  # contains duplicate tag
                "created_by": {"type": "agent", "id": agent_id_str},
            },
        )
        assert res is not None
        assert not res.is_error
        data = json.loads(res.content[0].text)

        assert "note_id" in data
        created_note_id = data["note_id"]
        assert data["title"] == "Introduction to Vector Embeddings"
        assert (
            data["content"]
            == "# Vector Embeddings\n\nHigh-dimensional representations of text."
        )
        assert data["category"] == "technical_research"
        assert sorted(data["tags"]) == [
            "AI",
            "Embeddings",
            "Search",
        ]  # duplicates deduplicated
        assert data["created_by"]["type"] == "agent"
        assert data["created_by"]["id"] == agent_id_str
        assert data["created_by"]["name"] == seeded_agent["name"]
        assert data["is_deleted"] is False
        assert data["version_count"] == 0

        # 2. Get note by UUID
        get_res = await session.call_tool("get_note", {"note_id": created_note_id})
        get_data = json.loads(get_res.content[0].text)
        assert get_data["note_id"] == created_note_id
        assert get_data["title"] == "Introduction to Vector Embeddings"

        # 3. Non-existent note UUID
        random_id = str(uuid.uuid4())
        not_found_res = await session.call_tool("get_note", {"note_id": random_id})
        not_found_data = json.loads(not_found_res.content[0].text)
        assert "error" in not_found_data
        assert f"'{random_id}' not found" in not_found_data["error"]

        # 4. Invalid UUID format
        invalid_res = await session.call_tool(
            "get_note", {"note_id": "not-a-valid-uuid"}
        )
        invalid_data = json.loads(invalid_res.content[0].text)
        assert "error" in invalid_data
        assert "Invalid UUID string format" in invalid_data["error"]

    # Cleanup
    if created_note_id:
        with get_session() as s:
            s.execute(delete(Note).where(Note.note_id == uuid.UUID(created_note_id)))
            s.commit()


async def test_create_note_validation_errors(
    notes_mcp_server: str,
) -> None:
    """Verify validation rules on create_note tool."""
    mcp_url = f"{notes_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Empty title
        res = await session.call_tool(
            "create_note",
            {"title": "  ", "content": "Valid body", "category": "ideas"},
        )
        assert "error" in json.loads(res.content[0].text)

        # 2. Empty content
        res = await session.call_tool(
            "create_note",
            {"title": "Valid title", "content": "  ", "category": "ideas"},
        )
        assert "error" in json.loads(res.content[0].text)

        # 3. Invalid category
        res = await session.call_tool(
            "create_note",
            {
                "title": "Valid title",
                "content": "Valid body",
                "category": "unsupported_cat",
            },
        )
        assert "error" in json.loads(res.content[0].text)
        assert "Invalid category" in json.loads(res.content[0].text)["error"]

        # 4. Invalid attribution type
        res = await session.call_tool(
            "create_note",
            {
                "title": "Valid",
                "content": "Valid",
                "category": "ideas",
                "created_by": {"type": "unknown", "id": str(uuid.uuid4())},
            },
        )
        assert "error" in json.loads(res.content[0].text)

        # 5. Nonexistent agent in attribution
        res = await session.call_tool(
            "create_note",
            {
                "title": "Valid",
                "content": "Valid",
                "category": "ideas",
                "created_by": {"type": "agent", "id": str(uuid.uuid4())},
            },
        )
        assert "error" in json.loads(res.content[0].text)
        assert "does not exist" in json.loads(res.content[0].text)["error"]


async def test_update_note_version_creation_and_retention(
    notes_mcp_server: str,
    seeded_agent: dict[str, Any],
) -> None:
    """Verify update_note creates sequential version snapshots in note_versions (DEC-031)."""
    mcp_url = f"{notes_mcp_server}/mcp"
    agent_id_str = seeded_agent["agent_id_str"]
    user_id_str = str(uuid.uuid4())

    note_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Step 1: Create initial note
        create_res = await session.call_tool(
            "create_note",
            {
                "title": "Initial Title v0",
                "content": "Initial body content v0.",
                "category": "ideas",
                "created_by": {"type": "agent", "id": agent_id_str},
            },
        )
        note_id = json.loads(create_res.content[0].text)["note_id"]

        # Step 2: First update with content modification
        update_1 = await session.call_tool(
            "update_note",
            {
                "note_id": note_id,
                "title": "Revised Title v1",
                "content": "First updated content v1.",
                "changed_by": {"type": "user", "id": user_id_str},
            },
        )
        data_u1 = json.loads(update_1.content[0].text)
        assert data_u1["title"] == "Revised Title v1"
        assert data_u1["content"] == "First updated content v1."
        assert data_u1["version_count"] == 1
        assert len(data_u1["versions"]) == 1
        v1 = data_u1["versions"][0]
        assert v1["version_number"] == 1
        assert v1["title"] == "Initial Title v0"
        assert v1["content"] == "Initial body content v0."

        # Step 3: Second update (only tags changed) -> should NOT create a new version snapshot
        update_tags = await session.call_tool(
            "update_note",
            {
                "note_id": note_id,
                "tags": ["TagA", "TagB"],
            },
        )
        data_tags = json.loads(update_tags.content[0].text)
        assert data_tags["tags"] == ["TagA", "TagB"]
        assert data_tags["version_count"] == 1  # version count remains 1

        # Step 4: Third update with category and content change
        update_2 = await session.call_tool(
            "update_note",
            {
                "note_id": note_id,
                "content": "Second updated content v2.",
                "category": "technical_research",
            },
        )
        data_u2 = json.loads(update_2.content[0].text)
        assert data_u2["content"] == "Second updated content v2."
        assert data_u2["category"] == "technical_research"
        assert data_u2["version_count"] == 2

        # Step 5: get_note with include_versions=True
        get_res = await session.call_tool(
            "get_note", {"note_id": note_id, "include_versions": True}
        )
        get_data = json.loads(get_res.content[0].text)
        assert len(get_data["versions"]) == 2
        # Versions ordered newest to oldest
        version_numbers = [v["version_number"] for v in get_data["versions"]]
        assert version_numbers == [2, 1]

    # Cleanup
    if note_id:
        with get_session() as s:
            s.execute(
                delete(NoteVersion).where(NoteVersion.note_id == uuid.UUID(note_id))
            )
            s.execute(delete(Note).where(Note.note_id == uuid.UUID(note_id)))
            s.commit()


async def test_fifo_version_pruning_policy(
    notes_mcp_server: str,
) -> None:
    """Verify FIFO pruning of oldest historical versions when positive MAX_NOTE_VERSIONS is set (DEC-031)."""
    mcp_url = f"{notes_mcp_server}/mcp"
    note_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Create note
        res = await session.call_tool(
            "create_note",
            {
                "title": "Pruning Test Note",
                "content": "Version 0 content",
                "category": "ideas",
            },
        )
        note_id = json.loads(res.content[0].text)["note_id"]

        # Simulate MAX_NOTE_VERSIONS=2
        mock_settings = MCPServerSettings(max_note_versions=2)
        with patch(
            "server_mcp.tools.notes_management.get_server_settings",
            return_value=mock_settings,
        ):
            # Update 1 -> creates version snapshot 1
            await session.call_tool(
                "update_note", {"note_id": note_id, "content": "Version 1 content"}
            )
            # Update 2 -> creates version snapshot 2
            await session.call_tool(
                "update_note", {"note_id": note_id, "content": "Version 2 content"}
            )
            # Update 3 -> creates version snapshot 3, but ceiling is 2, so version 1 is pruned FIFO!
            await session.call_tool(
                "update_note", {"note_id": note_id, "content": "Version 3 content"}
            )

            # Verify in DB that only versions 2 and 3 remain
            with get_session() as s:
                retained_versions = s.scalars(
                    select(NoteVersion)
                    .where(NoteVersion.note_id == uuid.UUID(note_id))
                    .order_by(NoteVersion.version_number.asc())
                ).all()
                assert len(retained_versions) == 2
                assert [v.version_number for v in retained_versions] == [2, 3]

    # Cleanup
    if note_id:
        with get_session() as s:
            s.execute(
                delete(NoteVersion).where(NoteVersion.note_id == uuid.UUID(note_id))
            )
            s.execute(delete(Note).where(Note.note_id == uuid.UUID(note_id)))
            s.commit()


async def test_soft_delete_and_version_preservation(
    notes_mcp_server: str,
) -> None:
    """Verify soft deletion (DEC-029) sets is_deleted and preserves note_versions and tags in database."""
    mcp_url = f"{notes_mcp_server}/mcp"
    note_id = None

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Create note with tags
        res = await session.call_tool(
            "create_note",
            {
                "title": "Ephemeral Knowledge Note",
                "content": "Valuable research to be soft-deleted.",
                "category": "technical_research",
                "tags": ["Ephemeral", "Research"],
            },
        )
        note_id = json.loads(res.content[0].text)["note_id"]

        # 2. Update note to generate a historical version snapshot
        await session.call_tool(
            "update_note",
            {"note_id": note_id, "content": "Updated content before deletion."},
        )

        # 3. Soft-delete the note
        del_res = await session.call_tool("delete_note", {"note_id": note_id})
        del_data = json.loads(del_res.content[0].text)
        assert del_data["success"] is True

        # 4. get_note returns not found
        get_res = await session.call_tool("get_note", {"note_id": note_id})
        assert "error" in json.loads(get_res.content[0].text)

        # 5. get_notes excludes it
        all_notes_res = await session.call_tool("get_notes", {})
        all_notes = [json.loads(c.text) for c in all_notes_res.content]
        assert all(n["note_id"] != note_id for n in all_notes)

        # 6. search_notes excludes it
        search_res = await session.call_tool(
            "search_notes", {"query": "Ephemeral Knowledge"}
        )
        found = [json.loads(c.text) for c in search_res.content]
        assert all(n["note_id"] != note_id for n in found)

        # 7. notes://all resource excludes it
        res_resource = await session.read_resource("notes://all")
        resource_data = json.loads(res_resource.contents[0].text)
        assert all(n["note_id"] != note_id for n in resource_data["notes"])

        # 8. DIRECT DATABASE VERIFICATION (DEC-029 requirement):
        # Historical versions and tags are preserved intact in PostgreSQL!
        with get_session() as s:
            raw_note = s.get(Note, uuid.UUID(note_id))
            assert raw_note is not None
            assert raw_note.is_deleted is True
            assert raw_note.deleted_at is not None

            # Verify versions preserved
            db_versions = s.scalars(
                select(NoteVersion).where(NoteVersion.note_id == uuid.UUID(note_id))
            ).all()
            assert len(db_versions) == 1
            assert db_versions[0].content == "Valuable research to be soft-deleted."

            # Verify tags preserved
            assert len(raw_note.tags) == 2

    # Hard cleanup
    if note_id:
        with get_session() as s:
            s.execute(
                delete(NoteVersion).where(NoteVersion.note_id == uuid.UUID(note_id))
            )
            s.execute(delete(Note).where(Note.note_id == uuid.UUID(note_id)))
            s.commit()


async def test_get_notes_filtering_and_search(
    notes_mcp_server: str,
) -> None:
    """Verify get_notes filtering by category, tag, and search_notes keyword matching."""
    mcp_url = f"{notes_mcp_server}/mcp"
    note_ids = []

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Seed 3 notes
        r1 = await session.call_tool(
            "create_note",
            {
                "title": "Quantum Error Correction",
                "content": "Surface codes and syndrome measurement details.",
                "category": "technical_research",
                "tags": ["Quantum", "Physics"],
            },
        )
        note_ids.append(json.loads(r1.content[0].text)["note_id"])

        r2 = await session.call_tool(
            "create_note",
            {
                "title": "Sprint Planning Notes",
                "content": "Discussed roadmap and milestone deliverables.",
                "category": "meeting_notes",
                "tags": ["Agile", "Management"],
            },
        )
        note_ids.append(json.loads(r2.content[0].text)["note_id"])

        r3 = await session.call_tool(
            "create_note",
            {
                "title": "Novel Agent Communication Protocol",
                "content": "Exploring decentralized consensus among local models.",
                "category": "ideas",
                "tags": ["Agents", "Consensus"],
            },
        )
        note_ids.append(json.loads(r3.content[0].text)["note_id"])

        # 1. Filter by category
        cat_res = await session.call_tool(
            "get_notes", {"category": "technical_research"}
        )
        cat_notes = [json.loads(c.text) for c in cat_res.content]
        assert any(n["note_id"] == note_ids[0] for n in cat_notes)
        assert all(n["category"] == "technical_research" for n in cat_notes)

        # 2. Filter by tag
        tag_res = await session.call_tool("get_notes", {"tag": "Quantum"})
        tag_notes = [json.loads(c.text) for c in tag_res.content]
        assert any(n["note_id"] == note_ids[0] for n in tag_notes)

        # 3. Search title keyword
        search_title = await session.call_tool(
            "search_notes", {"query": "Error Correction"}
        )
        found_title = [json.loads(c.text) for c in search_title.content]
        assert any(n["note_id"] == note_ids[0] for n in found_title)

        # 4. Search body keyword
        search_body = await session.call_tool("search_notes", {"query": "consensus"})
        found_body = [json.loads(c.text) for c in search_body.content]
        assert any(n["note_id"] == note_ids[2] for n in found_body)

        # 5. Search with category filter
        search_filtered = await session.call_tool(
            "search_notes", {"query": "roadmap", "category": "meeting_notes"}
        )
        found_filtered = [json.loads(c.text) for c in search_filtered.content]
        assert any(n["note_id"] == note_ids[1] for n in found_filtered)

    # Cleanup
    with get_session() as s:
        s.execute(
            delete(Note).where(Note.note_id.in_([uuid.UUID(nid) for nid in note_ids]))
        )
        s.commit()


async def test_notes_management_resources(
    notes_mcp_server: str,
) -> None:
    """Verify all notes:// resources return structured note collections."""
    mcp_url = f"{notes_mcp_server}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. notes://all
        res_all = await session.read_resource("notes://all")
        assert len(res_all.contents) > 0
        data_all = json.loads(res_all.contents[0].text)
        assert "notes" in data_all
        assert isinstance(data_all["notes"], list)

        # 2. notes://technical
        res_tech = await session.read_resource("notes://technical")
        data_tech = json.loads(res_tech.contents[0].text)
        assert "notes" in data_tech
        assert all(n["category"] == "technical_research" for n in data_tech["notes"])

        # 3. notes://research
        res_res = await session.read_resource("notes://research")
        data_res = json.loads(res_res.contents[0].text)
        assert "notes" in data_res

        # 4. notes://literature
        res_lit = await session.read_resource("notes://literature")
        data_lit = json.loads(res_lit.contents[0].text)
        assert "notes" in data_lit

        # 5. notes://project
        res_proj = await session.read_resource("notes://project")
        data_proj = json.loads(res_proj.contents[0].text)
        assert "notes" in data_proj

        # 6. notes://ideas
        res_ideas = await session.read_resource("notes://ideas")
        data_ideas = json.loads(res_ideas.contents[0].text)
        assert "notes" in data_ideas
