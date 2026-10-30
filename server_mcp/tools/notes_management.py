"""Notes Management MCP tools for ResearchMate.

Implements the six tools specified in docs/MCP/Notes Management.md:
- create_note
- get_note
- get_notes
- update_note
- delete_note
- search_notes

Complies with:
- DEC-026: UUID standardization
- DEC-027: Unified Attribution object
- DEC-029: Soft deletion policy with version preservation
- DEC-031: Indefinite note version retention with configurable ceiling
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import Agent, Note, NoteTag, NoteVersion
from server_mcp.config import get_server_settings

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "technical_research",
    "project_documentation",
    "meeting_notes",
    "ideas",
    "general_knowledge",
    "personal_notes",
}


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


def _get_or_create_tags(tag_names: list[str], session: Any) -> list[NoteTag]:
    """Retrieve existing NoteTag entities or create new ones for distinct names."""
    clean_names = list(dict.fromkeys(t.strip() for t in tag_names if t and t.strip()))
    if not clean_names:
        return []

    existing_tags = session.scalars(
        select(NoteTag).where(NoteTag.name.in_(clean_names))
    ).all()
    existing_map = {t.name.lower(): t for t in existing_tags}

    result = []
    for name in clean_names:
        lower_name = name.lower()
        if lower_name in existing_map:
            result.append(existing_map[lower_name])
        else:
            new_tag = NoteTag(tag_id=uuid.uuid4(), name=name)
            session.add(new_tag)
            session.flush()
            existing_map[lower_name] = new_tag
            result.append(new_tag)
    return result


def _serialize_note(note: Note, include_versions: bool = False) -> dict[str, Any]:
    """Serialize a Note ORM instance into standard Note representation."""
    created_by = None
    if note.created_by_agent_id:
        created_by = {
            "type": "agent",
            "id": str(note.created_by_agent_id),
            "name": note.created_by_agent.name if note.created_by_agent else None,
        }
    elif note.created_by_user_id:
        created_by = {
            "type": "user",
            "id": str(note.created_by_user_id),
            "name": None,
        }

    tag_names = sorted([t.name for t in note.tags]) if note.tags else []

    data: dict[str, Any] = {
        "note_id": str(note.note_id),
        "title": note.title,
        "content": note.content,
        "category": note.category,
        "tags": tag_names,
        "created_by": created_by,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        "is_deleted": note.is_deleted,
        "deleted_at": note.deleted_at.isoformat() if note.deleted_at else None,
        "version_count": len(note.versions) if note.versions else 0,
    }

    if include_versions and note.versions:
        data["versions"] = [
            {
                "version_id": str(v.version_id),
                "version_number": v.version_number,
                "title": v.title,
                "content": v.content,
                "category": v.category,
                "changed_by": {
                    "type": "agent" if v.changed_by_agent_id else "user",
                    "id": str(v.changed_by_agent_id or v.changed_by_user_id),
                    "name": v.changed_by_agent.name if v.changed_by_agent else None,
                }
                if (v.changed_by_agent_id or v.changed_by_user_id)
                else None,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in note.versions
        ]

    return data


def register_notes_tools(server: MCPServer) -> None:
    """Register all 6 Notes Management MCP tools."""

    @server.tool(
        name="create_note",
        description="Create a new persistent research note in Markdown with tags and attribution.",
    )
    async def create_note(
        title: str,
        content: str,
        category: str,
        tags: list[str] | None = None,
        created_by: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new note in PostgreSQL."""
        if not title or not title.strip():
            return {"error": "Note title cannot be empty."}

        if not content or not content.strip():
            return {"error": "Note content cannot be empty."}

        cat_lower = category.lower().strip()
        if cat_lower not in VALID_CATEGORIES:
            return {
                "error": f"Invalid category: '{category}'. Valid categories: {sorted(VALID_CATEGORIES)}."
            }

        try:
            with get_session() as session:
                agent_id, user_id, err = _parse_attribution(
                    created_by, session, "created_by"
                )
                if err:
                    return {"error": err}

                new_note_id = uuid.uuid4()
                tag_entities = _get_or_create_tags(tags or [], session)

                note = Note(
                    note_id=new_note_id,
                    title=title.strip(),
                    content=content.strip(),
                    category=cat_lower,
                    created_by_agent_id=agent_id,
                    created_by_user_id=user_id,
                    tags=tag_entities,
                    is_deleted=False,
                )
                session.add(note)
                session.commit()

                # Re-query with relationships loaded
                saved_note = session.scalar(
                    select(Note)
                    .options(
                        joinedload(Note.created_by_agent),
                        selectinload(Note.tags),
                        selectinload(Note.versions),
                    )
                    .where(Note.note_id == new_note_id)
                )
                return _serialize_note(saved_note)

        except SQLAlchemyError as exc:
            logger.error("Database error creating note: %s", exc)
            return {"error": "Internal database error occurred while creating note."}

    @server.tool(
        name="get_note",
        description="Retrieve a single note by UUID, optionally including its version history.",
    )
    async def get_note(
        note_id: str,
        include_versions: bool = False,
    ) -> dict[str, Any]:
        """Fetch note details by UUID, excluding soft-deleted notes."""
        try:
            note_uuid = uuid.UUID(note_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{note_id}'."}

        try:
            with get_session() as session:
                note = session.scalar(
                    select(Note)
                    .options(
                        joinedload(Note.created_by_agent),
                        selectinload(Note.tags),
                        selectinload(Note.versions).joinedload(
                            NoteVersion.changed_by_agent
                        ),
                    )
                    .where(Note.note_id == note_uuid, Note.is_deleted.is_(False))
                )
                if not note:
                    return {"error": f"Note with id '{note_id}' not found."}
                return _serialize_note(note, include_versions=include_versions)

        except SQLAlchemyError as exc:
            logger.error("Database error retrieving note %s: %s", note_id, exc)
            return {"error": "Internal database error occurred while fetching note."}

    @server.tool(
        name="get_notes",
        description="Retrieve notes filtered by category, tag, or creator, excluding soft-deleted notes.",
    )
    async def get_notes(
        category: str | None = None,
        tag: str | None = None,
        created_by_agent_id: str | None = None,
        created_by_user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """List notes matching optional filters."""
        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)

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
                    .offset(bounded_offset)
                    .limit(bounded_limit)
                )

                if category:
                    cat_lower = category.lower().strip()
                    if cat_lower not in VALID_CATEGORIES:
                        return {"error": f"Invalid category filter: '{category}'."}
                    query = query.where(Note.category == cat_lower)

                if tag:
                    tag_clean = tag.strip()
                    query = query.where(Note.tags.any(NoteTag.name.ilike(tag_clean)))

                if created_by_agent_id:
                    try:
                        agent_uuid = uuid.UUID(created_by_agent_id.strip())
                        query = query.where(Note.created_by_agent_id == agent_uuid)
                    except (ValueError, TypeError):
                        return {
                            "error": f"Invalid created_by_agent_id UUID: '{created_by_agent_id}'."
                        }

                if created_by_user_id:
                    try:
                        user_uuid = uuid.UUID(created_by_user_id.strip())
                        query = query.where(Note.created_by_user_id == user_uuid)
                    except (ValueError, TypeError):
                        return {
                            "error": f"Invalid created_by_user_id UUID: '{created_by_user_id}'."
                        }

                notes = session.scalars(query).all()
                return [_serialize_note(n) for n in notes]

        except SQLAlchemyError as exc:
            logger.error("Database error listing notes: %s", exc)
            return {"error": "Internal database error occurred while querying notes."}

    @server.tool(
        name="update_note",
        description="Update an existing note's content or metadata, preserving version history (DEC-029, DEC-031).",
    )
    async def update_note(
        note_id: str,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        changed_by: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a note, archiving previous content into note_versions."""
        try:
            note_uuid = uuid.UUID(note_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{note_id}'."}

        try:
            with get_session() as session:
                note = session.scalar(
                    select(Note)
                    .options(
                        joinedload(Note.created_by_agent),
                        selectinload(Note.tags),
                        selectinload(Note.versions),
                    )
                    .where(Note.note_id == note_uuid, Note.is_deleted.is_(False))
                )
                if not note:
                    return {"error": f"Note with id '{note_id}' not found."}

                # Validate changed_by attribution if supplied
                changed_agent_id, changed_user_id, err = _parse_attribution(
                    changed_by, session, "changed_by"
                )
                if err:
                    return {"error": err}

                # Check if content, title, or category changed
                title_changed = (
                    title is not None and title.strip() and title.strip() != note.title
                )
                content_changed = (
                    content is not None
                    and content.strip()
                    and content.strip() != note.content
                )
                cat_lower = category.lower().strip() if category else None
                if cat_lower and cat_lower not in VALID_CATEGORIES:
                    return {
                        "error": f"Invalid category: '{category}'. Valid categories: {sorted(VALID_CATEGORIES)}."
                    }
                category_changed = cat_lower is not None and cat_lower != note.category

                # Create version snapshot only if substantive content changed
                if title_changed or content_changed or category_changed:
                    # Determine next version number
                    max_v = session.scalar(
                        select(
                            func.coalesce(func.max(NoteVersion.version_number), 0)
                        ).where(NoteVersion.note_id == note_uuid)
                    )
                    new_version_num = (max_v or 0) + 1

                    if changed_agent_id is not None or changed_user_id is not None:
                        v_agent_id = changed_agent_id
                        v_user_id = changed_user_id
                    else:
                        v_agent_id = note.created_by_agent_id
                        v_user_id = note.created_by_user_id

                    snapshot = NoteVersion(
                        version_id=uuid.uuid4(),
                        note_id=note_uuid,
                        version_number=new_version_num,
                        title=note.title,
                        content=note.content,
                        category=note.category,
                        changed_by_agent_id=v_agent_id,
                        changed_by_user_id=v_user_id,
                        created_at=datetime.now(UTC),
                    )
                    session.add(snapshot)
                    session.flush()

                    # Apply MAX_NOTE_VERSIONS pruning policy (DEC-031)
                    settings = get_server_settings()
                    max_versions = settings.max_note_versions
                    if max_versions > 0:
                        all_versions = session.scalars(
                            select(NoteVersion)
                            .where(NoteVersion.note_id == note_uuid)
                            .order_by(NoteVersion.version_number.asc())
                        ).all()
                        if len(all_versions) > max_versions:
                            to_prune = len(all_versions) - max_versions
                            for v in all_versions[:to_prune]:
                                session.delete(v)
                            session.flush()

                # Apply updates to active note
                if title_changed:
                    note.title = title.strip()
                if content_changed:
                    note.content = content.strip()
                if category_changed:
                    note.category = cat_lower

                # Update tags if provided
                if tags is not None:
                    note.tags = _get_or_create_tags(tags, session)

                note.updated_at = datetime.now(UTC)
                session.commit()

                # Refresh and return
                refreshed = session.scalar(
                    select(Note)
                    .options(
                        joinedload(Note.created_by_agent),
                        selectinload(Note.tags),
                        selectinload(Note.versions),
                    )
                    .where(Note.note_id == note_uuid)
                )
                return _serialize_note(refreshed, include_versions=True)

        except SQLAlchemyError as exc:
            logger.error("Database error updating note %s: %s", note_id, exc)
            return {"error": "Internal database error occurred while updating note."}

    @server.tool(
        name="delete_note",
        description="Soft delete a note by UUID, preserving version history and tags (DEC-029).",
    )
    async def delete_note(note_id: str) -> dict[str, Any]:
        """Soft delete a note by marking is_deleted=True and setting deleted_at."""
        try:
            note_uuid = uuid.UUID(note_id.strip())
        except (ValueError, TypeError, AttributeError):
            return {"error": f"Invalid UUID string format: '{note_id}'."}

        try:
            with get_session() as session:
                note = session.scalar(
                    select(Note).where(
                        Note.note_id == note_uuid, Note.is_deleted.is_(False)
                    )
                )
                if not note:
                    return {"error": f"Note with id '{note_id}' not found."}

                note.is_deleted = True
                note.deleted_at = datetime.now(UTC)
                note.updated_at = datetime.now(UTC)
                session.commit()

                return {
                    "success": True,
                    "message": f"Note '{note_id}' soft-deleted successfully.",
                    "note_id": note_id,
                }
        except SQLAlchemyError as exc:
            logger.error("Database error deleting note %s: %s", note_id, exc)
            return {"error": "Internal database error occurred while deleting note."}

    @server.tool(
        name="search_notes",
        description="Search non-deleted notes by keyword matching title or Markdown content.",
    )
    async def search_notes(
        query: str,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Search notes using case-insensitive substring matching across title and content."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return {"error": "Search query cannot be empty."}

        bounded_limit = max(1, min(limit, 200))

        try:
            with get_session() as session:
                search_filter = or_(
                    Note.title.ilike(f"%{cleaned_query}%"),
                    Note.content.ilike(f"%{cleaned_query}%"),
                )
                stmt = (
                    select(Note)
                    .options(
                        joinedload(Note.created_by_agent),
                        selectinload(Note.tags),
                        selectinload(Note.versions),
                    )
                    .where(Note.is_deleted.is_(False), search_filter)
                    .order_by(Note.updated_at.desc())
                    .limit(bounded_limit)
                )

                if category:
                    cat_lower = category.lower().strip()
                    if cat_lower not in VALID_CATEGORIES:
                        return {"error": f"Invalid category filter: '{category}'."}
                    stmt = stmt.where(Note.category == cat_lower)

                if tag:
                    tag_clean = tag.strip()
                    stmt = stmt.where(Note.tags.any(NoteTag.name.ilike(tag_clean)))

                notes = session.scalars(stmt).all()
                return [_serialize_note(n) for n in notes]

        except SQLAlchemyError as exc:
            logger.error("Database error searching notes: %s", exc)
            return {"error": "Internal database error occurred while searching notes."}
