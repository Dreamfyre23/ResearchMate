"""Unit tests for Phase 11 lifecycle management and pre-flight checks (DEC-033)."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client_mcp.host import MCPHost
from client_mcp.models import ResourceReadResult
from mas.config.settings import GeminiSettings
from mas.lifecycle import (
    check_database_status_via_mcp,
    check_gemini_configuration,
    check_mcp_server_health,
    ensure_workspace_structure,
    run_preflight_checks,
)


def test_mas_phase11_architectural_boundaries() -> None:
    """Verify that mas/lifecycle.py and mas/cli.py do not import forbidden modules."""
    files_to_check = [
        Path("mas/lifecycle.py"),
        Path("mas/cli.py"),
        Path("mas/orchestrator/conversation.py"),
        Path("mas/__main__.py"),
    ]
    forbidden_modules = {"server_mcp", "database"}

    for file_path in files_to_check:
        assert file_path.exists(), f"Expected file {file_path} to exist"
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    assert top_level not in forbidden_modules, (
                        f"Architecture violation: {file_path.name} imports forbidden module '{alias.name}'"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level = node.module.split(".")[0]
                assert top_level not in forbidden_modules, (
                    f"Architecture violation: {file_path.name} imports from forbidden module '{node.module}'"
                )


def test_ensure_workspace_structure(tmp_path: Path) -> None:
    """Verify workspace structure initialization safely creates the 4 standard subdirectories."""
    test_root = tmp_path / "test_workspace"
    assert not test_root.exists()

    result = ensure_workspace_structure(test_root)
    assert result is True
    assert test_root.exists()

    for subdir in ("documents", "reports", "datasets", "source_code"):
        subpath = test_root / subdir
        assert subpath.is_dir(), f"Expected subdirectory {subdir} was not created"

    # Verify idempotence (calling again on existing structure succeeds without errors)
    assert ensure_workspace_structure(test_root) is True


async def test_check_mcp_server_health_success() -> None:
    """Verify check_mcp_server_health returns True when HTTP health endpoint responds 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        ok, msg = await check_mcp_server_health("http://127.0.0.1:8000/mcp")
        assert ok is True
        assert "online (ok)" in msg


async def test_check_mcp_server_health_failure() -> None:
    """Verify check_mcp_server_health returns False when connection fails."""
    import httpx

    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("Refused"),
    ):
        ok, msg = await check_mcp_server_health("http://127.0.0.1:8000/mcp")
        assert ok is False
        assert "Cannot connect" in msg


def test_check_gemini_configuration_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Gemini check succeeds when API key is provided."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSyTestValidKey12345")
    ok, msg = check_gemini_configuration()
    assert ok is True
    assert "configured" in msg


def test_check_gemini_configuration_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Gemini check returns False and diagnostic warning when unconfigured."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Monkeypatch get_gemini_settings to return empty key
    with patch(
        "mas.lifecycle.get_gemini_settings", return_value=GeminiSettings(api_key=None)
    ):
        ok, msg = check_gemini_configuration()
        assert ok is False
        assert "fallback" in msg


async def test_check_database_status_via_mcp_connected() -> None:
    """Verify database check succeeds when system://database-info reports connected."""
    mock_host = MagicMock(spec=MCPHost)
    mock_result = ResourceReadResult(
        uri="system://database-info",
        mime_type="application/json",
        data={
            "status": "connected",
            "connected": True,
            "database_version": "PostgreSQL 18.0",
        },
    )
    mock_host.read_resource = AsyncMock(return_value=mock_result)

    ok, msg = await check_database_status_via_mcp(mock_host)
    assert ok is True
    assert "PostgreSQL" in msg


async def test_check_database_status_via_mcp_failure() -> None:
    """Verify database check returns False when database is unreachable."""
    mock_host = MagicMock(spec=MCPHost)
    mock_host.read_resource = AsyncMock(
        side_effect=Exception("Database connection refused")
    )

    ok, msg = await check_database_status_via_mcp(mock_host)
    assert ok is False
    assert "Could not query database" in msg


async def test_run_preflight_checks_aggregation(tmp_path: Path) -> None:
    """Verify run_preflight_checks consolidates all service statuses (DEC-033: no Ollama)."""
    with (
        patch(
            "mas.lifecycle.check_mcp_server_health",
            new_callable=AsyncMock,
            return_value=(True, "MCP OK"),
        ),
        patch(
            "mas.lifecycle.check_gemini_configuration", return_value=(True, "Gemini OK")
        ),
    ):
        health = await run_preflight_checks(workspace_root=tmp_path)
        assert health.workspace is True
        assert health.mcp_server is True
        assert health.gemini is True
        assert health.is_operational is True
        # ollama field is no longer present on ServiceHealth (DEC-033)
        assert not hasattr(health, "ollama")
