"""File Management MCP tools for ResearchMate.

Implements the four read-only tools specified in docs/MCP/File Management.md:
- list_files
- read_file
- search_files
- get_file_metadata

Complies with:
- DEC-032: Workspace scope and supported file operations (read-only for TXT, MD, JSON, CSV, PY, SQL)
- Strict workspace root boundary enforcement (no path traversal, symlink escapes, or absolute paths)
- Safe handling of oversized files, encoding errors, and non-existent paths
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from server_mcp.config import MCPServerSettings, get_server_settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".py", ".sql"}
STANDARD_SUBDIRECTORIES = ["documents", "reports", "datasets", "source_code"]


def get_workspace_root() -> Path:
    """Resolve the absolute Path of the configured workspace root (DEC-032)."""
    settings = get_server_settings()
    return Path(settings.workspace_root).resolve()


def ensure_workspace_directories(root_override: Path | None = None) -> list[Path]:
    """Ensure the four permanent workspace subdirectories exist safely (DEC-032)."""
    root = (root_override or get_workspace_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created_or_verified = []
    for sub in STANDARD_SUBDIRECTORIES:
        sub_dir = root / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        created_or_verified.append(sub_dir)
    return created_or_verified


def _validate_and_resolve_path(
    user_path: str,
    workspace_root: Path,
    must_exist: bool = True,
    allow_dir: bool = False,
) -> tuple[Path | None, str | None, str | None]:
    """Validate that a user-supplied path resides strictly within the workspace.

    Returns:
        (resolved_path, relative_path_str, error_message)
    """
    if user_path is None:
        return None, None, "Path parameter cannot be null."

    cleaned_path = user_path.strip()
    if not cleaned_path and not allow_dir:
        return None, None, "Path cannot be empty."

    path_obj = Path(cleaned_path)
    if (
        path_obj.is_absolute()
        or cleaned_path.startswith(("/", "\\"))
        or (len(cleaned_path) > 1 and cleaned_path[1] == ":")
    ):
        return (
            None,
            None,
            f"Absolute paths are not permitted: '{user_path}'. Paths must be relative to the workspace root.",
        )

    # Reject traversal sequences in input parts
    if ".." in path_obj.parts:
        return (
            None,
            None,
            f"Path traversal sequences ('..') are not permitted: '{user_path}'.",
        )

    root_resolved = workspace_root.resolve()
    candidate = root_resolved / path_obj

    # Check existence if required
    if must_exist and not candidate.exists() and not candidate.is_symlink():
        return None, None, f"File or directory not found: '{user_path}'."

    # Resolve symlinks and canonical path
    resolved = candidate.resolve()

    # Enforce workspace root boundary
    try:
        rel_path = resolved.relative_to(root_resolved)
    except ValueError:
        return (
            None,
            None,
            f"Access denied: path '{user_path}' resolves outside the permitted workspace root.",
        )

    # Symlink escape verification: check if symlink target points outside workspace
    if candidate.is_symlink():
        try:
            candidate.resolve().relative_to(root_resolved)
        except ValueError:
            return (
                None,
                None,
                f"Access denied: symlink '{user_path}' points outside the permitted workspace root.",
            )

    rel_str = str(rel_path).replace("\\", "/") if str(rel_path) != "." else ""

    # Directory check
    if not allow_dir:
        if resolved.is_dir():
            return None, None, f"Path '{user_path}' is a directory, not a file."

        suffix = resolved.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            return (
                None,
                None,
                f"Unsupported file extension '{suffix}'. Supported formats: {sorted(SUPPORTED_EXTENSIONS)}.",
            )

    return resolved, rel_str, None


def _read_file_content_sync(file_path: Path) -> str:
    """Synchronous file content reader for thread execution."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def _search_files_sync(
    resolved_dir: Path,
    ws_root: Path,
    cleaned_query: str | None,
    normalized_ext: str | None,
    search_content: bool,
    bounded_limit: int,
    max_file_size_bytes: int,
) -> list[dict[str, Any]]:
    """Synchronous file search walker for thread execution."""
    matches: list[dict[str, Any]] = []

    for item in resolved_dir.rglob("*"):
        if item.is_dir() or item.name.startswith("."):
            continue

        try:
            rel_to_search = item.relative_to(resolved_dir)
            if any(part.startswith(".") for part in rel_to_search.parts):
                continue
        except ValueError:
            continue

        if item.is_symlink():
            try:
                item.resolve().relative_to(ws_root)
            except ValueError:
                continue

        ext = item.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        if normalized_ext and ext != normalized_ext:
            continue

        item_rel = str(item.resolve().relative_to(ws_root)).replace("\\", "/")

        if not cleaned_query:
            matches.append(
                {
                    "file_name": item.name,
                    "file_path": item_rel,
                    "extension": ext,
                    "match_type": "extension",
                    "excerpt": None,
                }
            )
            if len(matches) >= bounded_limit:
                break
            continue

        query_lower = cleaned_query.lower()

        # 1. Match filename
        if query_lower in item.name.lower():
            matches.append(
                {
                    "file_name": item.name,
                    "file_path": item_rel,
                    "extension": ext,
                    "match_type": "filename",
                    "excerpt": None,
                }
            )
            if len(matches) >= bounded_limit:
                break
            continue

        # 2. Match content if enabled
        if search_content:
            try:
                size = item.stat().st_size
                if size > max_file_size_bytes:
                    continue

                with open(item, "r", encoding="utf-8", errors="ignore") as f:
                    file_text = f.read()

                idx = file_text.lower().find(query_lower)
                if idx != -1:
                    start = max(0, idx - 40)
                    end = min(len(file_text), idx + len(query_lower) + 40)
                    excerpt = file_text[start:end].replace("\n", " ").strip()
                    matches.append(
                        {
                            "file_name": item.name,
                            "file_path": item_rel,
                            "extension": ext,
                            "match_type": "content",
                            "excerpt": f"...{excerpt}..."
                            if start > 0
                            else f"{excerpt}...",
                        }
                    )
                    if len(matches) >= bounded_limit:
                        break
            except OSError:
                continue

    return matches


def register_file_tools(
    server: MCPServer,
    settings: MCPServerSettings | None = None,
) -> None:
    """Register all 4 read-only File Management MCP tools."""

    def _get_root() -> Path:
        if settings is not None:
            return Path(settings.workspace_root).resolve()
        return get_workspace_root()

    def _get_max_size() -> int:
        if settings is not None:
            return settings.max_file_size_bytes
        return get_server_settings().max_file_size_bytes

    @server.tool(
        name="list_files",
        description="List files and subdirectories within a specified workspace directory (read-only, DEC-032).",
    )
    async def list_files(
        directory: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        """List permitted files and directories in workspace."""
        bounded_limit = max(1, min(limit, 1000))
        ws_root = _get_root()
        ensure_workspace_directories(ws_root)

        # Validate directory
        resolved_dir, rel_dir, err = _validate_and_resolve_path(
            directory, ws_root, must_exist=True, allow_dir=True
        )
        if err:
            return {"error": err}

        if not resolved_dir.is_dir():
            return {"error": f"Path '{directory}' is not a directory."}

        entries: list[dict[str, Any]] = []

        try:
            for item in resolved_dir.iterdir():
                if item.name.startswith("."):
                    continue

                if item.is_symlink():
                    try:
                        item.resolve().relative_to(ws_root)
                    except ValueError:
                        continue

                item_rel = str(item.resolve().relative_to(ws_root)).replace("\\", "/")

                if item.is_dir():
                    entries.append(
                        {
                            "name": item.name,
                            "path": item_rel,
                            "type": "directory",
                        }
                    )
                elif item.is_file():
                    ext = item.suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        try:
                            size = item.stat().st_size
                        except OSError:
                            size = 0
                        entries.append(
                            {
                                "name": item.name,
                                "path": item_rel,
                                "type": "file",
                                "size_bytes": size,
                                "extension": ext,
                            }
                        )

                if len(entries) >= bounded_limit:
                    break

        except OSError as exc:
            logger.error("Error listing directory %s: %s", directory, exc)
            return {"error": f"Failed to list directory: {exc}."}

        entries.sort(
            key=lambda e: (0 if e["type"] == "directory" else 1, e["name"].lower())
        )

        return {
            "directory": rel_dir,
            "total_entries": len(entries),
            "entries": entries,
        }

    @server.tool(
        name="read_file",
        description="Read the contents of a permitted text file in the workspace (read-only, DEC-032).",
    )
    async def read_file(
        file_path: str,
    ) -> dict[str, Any]:
        """Read content of a supported workspace file."""
        ws_root = _get_root()
        max_size = _get_max_size()

        resolved_file, rel_path, err = _validate_and_resolve_path(
            file_path, ws_root, must_exist=True, allow_dir=False
        )
        if err:
            return {"error": err}

        try:
            file_size = resolved_file.stat().st_size
        except OSError as exc:
            return {"error": f"Failed to inspect file '{file_path}': {exc}."}

        if file_size > max_size:
            return {
                "error": (
                    f"File size ({file_size} bytes) exceeds the maximum allowed limit "
                    f"({max_size} bytes)."
                )
            }

        try:
            content = await asyncio.to_thread(_read_file_content_sync, resolved_file)
        except UnicodeDecodeError as exc:
            return {"error": f"Failed to decode file '{file_path}' as UTF-8: {exc}."}
        except OSError as exc:
            return {"error": f"Failed to read file '{file_path}': {exc}."}

        return {
            "file_path": rel_path,
            "file_name": resolved_file.name,
            "extension": resolved_file.suffix.lower(),
            "size_bytes": file_size,
            "content": content,
        }

    @server.tool(
        name="search_files",
        description="Search permitted files by keyword in filename or content within the workspace (read-only, DEC-032).",
    )
    async def search_files(
        query: str | None = None,
        file_type: str | None = None,
        search_content: bool = True,
        directory: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search files by name or content within permitted workspace directories."""
        bounded_limit = max(1, min(limit, 200))
        ws_root = _get_root()
        max_size = _get_max_size()

        resolved_dir, rel_dir, err = _validate_and_resolve_path(
            directory, ws_root, must_exist=True, allow_dir=True
        )
        if err:
            return {"error": err}

        normalized_ext = None
        if file_type:
            cleaned_ext = file_type.lower().strip()
            if not cleaned_ext.startswith("."):
                cleaned_ext = f".{cleaned_ext}"
            if cleaned_ext not in SUPPORTED_EXTENSIONS:
                return {
                    "error": f"Unsupported file_type '{file_type}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}."
                }
            normalized_ext = cleaned_ext

        cleaned_query = query.strip() if query else None
        if not cleaned_query and not normalized_ext:
            return {"error": "Either query or file_type must be specified for search."}

        try:
            matches = await asyncio.to_thread(
                _search_files_sync,
                resolved_dir,
                ws_root,
                cleaned_query,
                normalized_ext,
                search_content,
                bounded_limit,
                max_size,
            )
        except OSError as exc:
            logger.error("Error during file search in %s: %s", directory, exc)
            return {"error": f"Search encountered an error: {exc}."}

        return {
            "query": cleaned_query,
            "directory": rel_dir,
            "total_matches": len(matches),
            "matches": matches,
        }

    @server.tool(
        name="get_file_metadata",
        description="Retrieve metadata (size, extension, modification time) for a workspace file (read-only, DEC-032).",
    )
    async def get_file_metadata(
        file_path: str,
    ) -> dict[str, Any]:
        """Fetch metadata for a permitted workspace file without reading entire content."""
        ws_root = _get_root()

        resolved_file, rel_path, err = _validate_and_resolve_path(
            file_path, ws_root, must_exist=True, allow_dir=False
        )
        if err:
            return {"error": err}

        try:
            stat = resolved_file.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            ctime = getattr(stat, "st_birthtime", stat.st_ctime)
            created_at = datetime.fromtimestamp(ctime, tz=UTC).isoformat()

            return {
                "file_name": resolved_file.name,
                "file_path": rel_path,
                "file_type": resolved_file.suffix.lower().lstrip("."),
                "extension": resolved_file.suffix.lower(),
                "file_size": stat.st_size,
                "created_at": created_at,
                "modified_at": modified_at,
            }
        except OSError as exc:
            logger.error("Error retrieving metadata for %s: %s", file_path, exc)
            return {"error": f"Failed to retrieve metadata: {exc}."}
