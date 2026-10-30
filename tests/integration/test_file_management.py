"""Integration tests for File Management MCP tools (Phase 7).

Validates:
- list_files across all four permanent workspace directories (DEC-032).
- read_file for all 6 supported extensions (.txt, .md, .json, .csv, .py, .sql).
- search_files by keyword across filename and content.
- get_file_metadata without reading full contents.
- Security constraints:
  - Unsupported file extensions (.pdf, .exe, .bin, .docx).
  - Absolute paths rejected.
  - Path traversal sequences ('..') rejected.
  - Nested traversal sequences rejected.
  - Symlinks pointing outside the workspace rejected.
  - Oversized file handling (exceeding MAX_FILE_SIZE_BYTES).
  - Invalid UTF-8 decoding handled safely.
  - Non-existent files/directories handled with clear errors.
- Read-only guarantees:
  - Verifying tool operations do not create, modify, rename, or delete files.
- Client session invocation over Streamable HTTP.
- Isolation using temporary workspace root.
"""

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from server_mcp.config import MCPServerSettings
from server_mcp.server import create_app
from server_mcp.tools.file_management import (
    _validate_and_resolve_path,
    ensure_workspace_directories,
)


def _find_free_port() -> int:
    """Find an available TCP port for ephemeral test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def isolated_workspace(tmp_path: Path) -> Path:
    """Create an isolated workspace populated with test files for all 6 supported formats."""
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    ensure_workspace_directories(ws)

    # 1. documents/ (Markdown and Plain text)
    (ws / "documents" / "guide.md").write_text(
        "# Research Guide\n\nHow to evaluate multi-agent orchestration.",
        encoding="utf-8",
    )
    (ws / "documents" / "notes.txt").write_text(
        "Important meeting notes regarding system architecture.",
        encoding="utf-8",
    )

    # 2. reports/ (Markdown)
    (ws / "reports" / "summary.md").write_text(
        "# Phase 7 Report\n\nFile Management component implementation overview.",
        encoding="utf-8",
    )

    # 3. datasets/ (CSV and JSON)
    (ws / "datasets" / "data.csv").write_text(
        "id,metric,score\n1,accuracy,0.95\n2,latency,12ms",
        encoding="utf-8",
    )
    (ws / "datasets" / "config.json").write_text(
        json.dumps({"pipeline": "mcp", "enabled": True, "workers": 4}),
        encoding="utf-8",
    )

    # 4. source_code/ (Python and SQL)
    (ws / "source_code" / "script.py").write_text(
        "def compute_metrics():\n    return {'f1': 0.92}\n",
        encoding="utf-8",
    )
    (ws / "source_code" / "schema.sql").write_text(
        "CREATE TABLE test_data (id INT PRIMARY KEY, name VARCHAR(50));",
        encoding="utf-8",
    )

    # 5. Nested directory inside documents/
    nested_dir = ws / "documents" / "sub_folder"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "nested_doc.md").write_text(
        "Nested Markdown document content.", encoding="utf-8"
    )

    return ws


@pytest.fixture
async def file_mcp_server(
    isolated_workspace: Path,
) -> AsyncGenerator[tuple[str, Path], None]:
    """Start an ephemeral MCP server pointed at the isolated workspace."""
    port = _find_free_port()
    host = "127.0.0.1"
    settings = MCPServerSettings(
        host=host,
        port=port,
        mcp_path="/mcp",
        server_name="ResearchMate-FileMgmt-Test",
        server_version="0.1.0-test",
        log_level="warning",
        workspace_root=str(isolated_workspace),
        max_file_size_bytes=1024 * 1024,  # 1MB limit for testing
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

    yield f"http://{host}:{port}", isolated_workspace

    server.should_exit = True
    await server_task


async def test_list_files_across_workspace(
    file_mcp_server: tuple[str, Path],
) -> None:
    """Verify list_files lists directories and supported files across the workspace."""
    base_url, _ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. List root directory
        res_root = await session.call_tool("list_files", {"directory": ""})
        data_root = json.loads(res_root.content[0].text)
        assert data_root["directory"] == ""
        dir_names = [
            e["name"] for e in data_root["entries"] if e["type"] == "directory"
        ]
        for sub in ("documents", "reports", "datasets", "source_code"):
            assert sub in dir_names

        # 2. List documents/ subdirectory
        res_docs = await session.call_tool("list_files", {"directory": "documents"})
        data_docs = json.loads(res_docs.content[0].text)
        assert data_docs["directory"] == "documents"
        entry_names = [e["name"] for e in data_docs["entries"]]
        assert "guide.md" in entry_names
        assert "notes.txt" in entry_names
        assert "sub_folder" in entry_names

        # 3. List nested directory
        res_nested = await session.call_tool(
            "list_files", {"directory": "documents/sub_folder"}
        )
        data_nested = json.loads(res_nested.content[0].text)
        assert data_nested["total_entries"] == 1
        assert data_nested["entries"][0]["name"] == "nested_doc.md"


async def test_read_file_supported_formats(
    file_mcp_server: tuple[str, Path],
) -> None:
    """Verify read_file reads all 6 supported extensions (.txt, .md, .json, .csv, .py, .sql)."""
    base_url, _ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    test_cases = [
        ("documents/guide.md", ".md", "Research Guide"),
        ("documents/notes.txt", ".txt", "Important meeting notes"),
        ("reports/summary.md", ".md", "Phase 7 Report"),
        ("datasets/data.csv", ".csv", "accuracy,0.95"),
        ("datasets/config.json", ".json", '"pipeline": "mcp"'),
        ("source_code/script.py", ".py", "def compute_metrics()"),
        ("source_code/schema.sql", ".sql", "CREATE TABLE test_data"),
    ]

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        for file_path, expected_ext, expected_text in test_cases:
            res = await session.call_tool("read_file", {"file_path": file_path})
            assert res is not None
            data = json.loads(res.content[0].text)
            assert "error" not in data
            assert data["extension"] == expected_ext
            assert data["file_path"] == file_path
            assert expected_text in data["content"]
            assert data["size_bytes"] > 0


async def test_search_files_filename_and_content(
    file_mcp_server: tuple[str, Path],
) -> None:
    """Verify search_files by keyword in filename and body content with file_type filters."""
    base_url, _ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Search by filename keyword
        res_fname = await session.call_tool(
            "search_files", {"query": "summary", "search_content": False}
        )
        data_fname = json.loads(res_fname.content[0].text)
        assert data_fname["total_matches"] >= 1
        assert any(m["file_name"] == "summary.md" for m in data_fname["matches"])

        # 2. Search by content keyword
        res_content = await session.call_tool(
            "search_files", {"query": "orchestration", "search_content": True}
        )
        data_content = json.loads(res_content.content[0].text)
        assert data_content["total_matches"] >= 1
        match = next(m for m in data_content["matches"] if m["file_name"] == "guide.md")
        assert match["match_type"] == "content"
        assert match["excerpt"] is not None

        # 3. Search filtered by file_type="py"
        res_py = await session.call_tool(
            "search_files", {"query": "metrics", "file_type": "py"}
        )
        data_py = json.loads(res_py.content[0].text)
        assert data_py["total_matches"] >= 1
        assert all(m["extension"] == ".py" for m in data_py["matches"])

        # 4. Search only by file_type="sql" with no query
        res_sql = await session.call_tool(
            "search_files", {"file_type": "sql", "search_content": False}
        )
        data_sql = json.loads(res_sql.content[0].text)
        assert data_sql["total_matches"] >= 1
        assert all(m["extension"] == ".sql" for m in data_sql["matches"])

        # 5. Search with no matches
        res_none = await session.call_tool(
            "search_files", {"query": "nonexistent_string_12345"}
        )
        data_none = json.loads(res_none.content[0].text)
        assert data_none["total_matches"] == 0
        assert data_none["matches"] == []


async def test_get_file_metadata(
    file_mcp_server: tuple[str, Path],
) -> None:
    """Verify get_file_metadata retrieves file properties without returning file content."""
    base_url, _ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        res = await session.call_tool(
            "get_file_metadata", {"file_path": "datasets/data.csv"}
        )
        data = json.loads(res.content[0].text)
        assert "error" not in data
        assert data["file_name"] == "data.csv"
        assert data["file_path"] == "datasets/data.csv"
        assert data["file_type"] == "csv"
        assert data["extension"] == ".csv"
        assert data["file_size"] > 0
        assert "created_at" in data
        assert "modified_at" in data
        # Ensure content is NOT included in metadata response
        assert "content" not in data


async def test_security_unsupported_extensions(
    file_mcp_server: tuple[str, Path],
    isolated_workspace: Path,
) -> None:
    """Verify unsupported file extensions are rejected (.pdf, .exe, .bin, .docx)."""
    base_url, ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    # Create unsupported test files inside workspace
    (ws / "documents" / "paper.pdf").write_bytes(b"%PDF-1.4 simulated pdf")
    (ws / "documents" / "binary.bin").write_bytes(b"\x00\x01\x02\x03")

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. read_file on .pdf
        res_pdf = await session.call_tool(
            "read_file", {"file_path": "documents/paper.pdf"}
        )
        assert (
            "Unsupported file extension" in json.loads(res_pdf.content[0].text)["error"]
        )

        # 2. get_file_metadata on .bin
        res_bin = await session.call_tool(
            "get_file_metadata", {"file_path": "documents/binary.bin"}
        )
        assert (
            "Unsupported file extension" in json.loads(res_bin.content[0].text)["error"]
        )

        # 3. list_files ignores unsupported files
        res_list = await session.call_tool("list_files", {"directory": "documents"})
        entries = json.loads(res_list.content[0].text)["entries"]
        assert all(e["name"] not in ("paper.pdf", "binary.bin") for e in entries)


async def test_security_path_traversal_and_absolute_paths(
    file_mcp_server: tuple[str, Path],
) -> None:
    """Verify absolute paths and traversal sequences ('..') are strictly rejected."""
    base_url, _ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # 1. Simple traversal
        res_trav = await session.call_tool("read_file", {"file_path": "../alembic.ini"})
        assert (
            "Path traversal sequences" in json.loads(res_trav.content[0].text)["error"]
        )

        # 2. Nested traversal
        res_nested_trav = await session.call_tool(
            "read_file", {"file_path": "documents/../../alembic.ini"}
        )
        assert (
            "Path traversal sequences"
            in json.loads(res_nested_trav.content[0].text)["error"]
        )

        # 3. Absolute path (Unix style)
        res_abs_unix = await session.call_tool(
            "read_file", {"file_path": "/etc/passwd"}
        )
        assert (
            "Absolute paths are not permitted"
            in json.loads(res_abs_unix.content[0].text)["error"]
        )

        # 4. Absolute path (Windows style)
        res_abs_win = await session.call_tool(
            "read_file", {"file_path": "C:\\Windows\\win.ini"}
        )
        assert (
            "Absolute paths are not permitted"
            in json.loads(res_abs_win.content[0].text)["error"]
        )


async def test_security_oversized_file(
    file_mcp_server: tuple[str, Path],
    isolated_workspace: Path,
) -> None:
    """Verify files exceeding max_file_size_bytes are rejected without truncation."""
    base_url, ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    # Server fixture sets max_file_size_bytes = 1MB. Create a 1.2MB file.
    big_file = ws / "datasets" / "big_dataset.csv"
    big_file.write_text("a,b,c\n" + ("1,2,3\n" * 200_000), encoding="utf-8")

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        res = await session.call_tool(
            "read_file", {"file_path": "datasets/big_dataset.csv"}
        )
        data = json.loads(res.content[0].text)
        assert "error" in data
        assert "exceeds the maximum allowed limit" in data["error"]


async def test_security_invalid_utf8(
    file_mcp_server: tuple[str, Path],
    isolated_workspace: Path,
) -> None:
    """Verify files with invalid UTF-8 bytes are handled safely with clear error."""
    base_url, ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    # Write invalid UTF-8 bytes to a supported extension
    bad_file = ws / "documents" / "corrupt.txt"
    bad_file.write_bytes(b"Valid start \xff\xfe\xfa corrupted bytes")

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        res = await session.call_tool(
            "read_file", {"file_path": "documents/corrupt.txt"}
        )
        data = json.loads(res.content[0].text)
        assert "error" in data
        assert "Failed to decode file" in data["error"]


async def test_security_symlink_escape_rejection(
    file_mcp_server: tuple[str, Path],
    isolated_workspace: Path,
    tmp_path: Path,
) -> None:
    """Verify symlinks pointing outside the workspace root are strictly rejected."""
    base_url, ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    # Create target outside workspace
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("Secret content outside workspace", encoding="utf-8")

    symlink_path = ws / "documents" / "symlink_escape.txt"

    try:
        symlink_path.symlink_to(outside_file)
    except (OSError, NotImplementedError) as exc:
        # Windows requires SeCreateSymbolicLinkPrivilege or Developer Mode
        pytest.skip(
            f"Symbolic link creation not permitted on this host ({exc}). "
            "Skipping symlink test per Windows OS permission boundaries."
        )

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        res = await session.call_tool(
            "read_file", {"file_path": "documents/symlink_escape.txt"}
        )
        data = json.loads(res.content[0].text)
        assert "error" in data
        assert "outside the permitted workspace root" in data["error"]


async def test_read_only_guarantee(
    file_mcp_server: tuple[str, Path],
    isolated_workspace: Path,
) -> None:
    """Verify File Management operations never create, modify, rename, or delete files."""
    base_url, ws = file_mcp_server
    mcp_url = f"{base_url}/mcp"

    target_file = ws / "documents" / "guide.md"
    initial_content = target_file.read_text(encoding="utf-8")
    initial_mtime = target_file.stat().st_mtime
    initial_files = set(ws.rglob("*"))

    async with (
        streamable_http_client(mcp_url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Run all four tools
        await session.call_tool("list_files", {"directory": "documents"})
        await session.call_tool("read_file", {"file_path": "documents/guide.md"})
        await session.call_tool("search_files", {"query": "guide"})
        await session.call_tool(
            "get_file_metadata", {"file_path": "documents/guide.md"}
        )

    # Post-execution assertions
    final_content = target_file.read_text(encoding="utf-8")
    final_mtime = target_file.stat().st_mtime
    final_files = set(ws.rglob("*"))

    assert final_content == initial_content
    assert final_mtime == initial_mtime
    assert final_files == initial_files


def test_symlink_escape_validation_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify _validate_and_resolve_path detects and rejects canonical paths outside the workspace root."""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("secret outside", encoding="utf-8")

    fake_symlink = ws / "symlink_file.txt"
    fake_symlink.write_text("stub", encoding="utf-8")

    # Mock Path.resolve so when resolving fake_symlink it returns the outside file
    orig_resolve = Path.resolve

    def mock_resolve(self: Path) -> Path:
        if self.name == "symlink_file.txt":
            return outside_file.resolve()
        return orig_resolve(self)

    monkeypatch.setattr(Path, "resolve", mock_resolve)

    resolved, rel, err = _validate_and_resolve_path(
        "symlink_file.txt", ws, must_exist=True
    )
    assert resolved is None
    assert rel is None
    assert err is not None
    assert "resolves outside the permitted workspace root" in err
