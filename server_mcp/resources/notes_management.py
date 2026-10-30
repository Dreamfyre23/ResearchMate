"""Notes Management MCP resources for ResearchMate.

Implements the resources specified in docs/MCP/Notes Management.md and Phase 6:
- notes://all
- notes://technical
- notes://research
- notes://literature
- notes://project
- notes://ideas

Complies with DEC-026 (UUID serialization) and DEC-029 (soft deletion exclusion).
"""

import json
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import Note
from server_mcp.tools.notes_management import _serialize_note

logger = logging.getLogger(__name__)


def _query_notes_with_filter(where_clause: Any | None = None) -> list[dict[str, Any]]:
    """Helper to query non-deleted notes with eager loading and serialize them."""
    try:
        with get_session() as session:
            query = (
                select(Note)
                .options(
                    joinedload(Note.created_by_agent),
                    selectinload(Note.tags),
                    selectinload(Note.versions),
                )
                .where(Note.is_deleted.is_(False))
                .order_by(Note.updated_at.desc())
            )
            if where_clause is not None:
                query = query.where(where_clause)

            notes = session.scalars(query).all()
            return [_serialize_note(n) for n in notes]
    except SQLAlchemyError as exc:
        logger.error("Failed to query notes for resource: %s", exc)
        return []


def register_notes_resources(server: MCPServer) -> None:
    """Register all Notes Management MCP resources."""

    @server.resource(
        "notes://all",
        name="All Notes",
        description="Collection of all active (non-deleted) research notes.",
        mime_type="application/json",
    )
    def resource_notes_all() -> str:
        return json.dumps({"notes": _query_notes_with_filter()}, indent=2)

    @server.resource(
        "notes://technical",
        name="Technical Notes",
        description="Notes classified under technical_research category.",
        mime_type="application/json",
    )
    def resource_notes_technical() -> str:
        return json.dumps(
            {"notes": _query_notes_with_filter(Note.category == "technical_research")},
            indent=2,
        )

    @server.resource(
        "notes://research",
        name="Research Notes",
        description="Notes classified under technical_research category.",
        mime_type="application/json",
    )
    def resource_notes_research() -> str:
        return json.dumps(
            {"notes": _query_notes_with_filter(Note.category == "technical_research")},
            indent=2,
        )

    @server.resource(
        "notes://literature",
        name="Literature Notes",
        description="Notes classified under general_knowledge or literature category.",
        mime_type="application/json",
    )
    def resource_notes_literature() -> str:
        return json.dumps(
            {"notes": _query_notes_with_filter(Note.category == "general_knowledge")},
            indent=2,
        )

    @server.resource(
        "notes://project",
        name="Project Documentation Notes",
        description="Notes classified under project_documentation category.",
        mime_type="application/json",
    )
    def resource_notes_project() -> str:
        return json.dumps(
            {
                "notes": _query_notes_with_filter(
                    Note.category == "project_documentation"
                )
            },
            indent=2,
        )

    @server.resource(
        "notes://ideas",
        name="Ideas Notes",
        description="Notes classified under ideas category.",
        mime_type="application/json",
    )
    def resource_notes_ideas() -> str:
        return json.dumps(
            {"notes": _query_notes_with_filter(Note.category == "ideas")},
            indent=2,
        )
