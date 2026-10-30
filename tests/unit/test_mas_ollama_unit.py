"""Unit tests for Ollama service integration in MAS (Phase 9).

Validates:
- OllamaSettings defaults and environment variable overrides.
- Health check behavior.
- Model listing and availability verification.
- Handling unavailable Ollama daemon (OllamaServiceUnavailableError).
- Handling model not found (OllamaModelNotFoundError).
- Handling timeouts (OllamaTimeoutError).
- Handling inference errors (OllamaInferenceError).
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from ollama._types import ResponseError

from mas.config.settings import OllamaSettings, get_ollama_settings
from mas.ollama.client import OllamaService
from mas.ollama.exceptions import (
    OllamaInferenceError,
    OllamaModelNotFoundError,
    OllamaServiceUnavailableError,
    OllamaTimeoutError,
)


def test_ollama_settings_defaults() -> None:
    """Verify default Ollama settings match DEC-009 requirements."""
    settings = OllamaSettings()
    assert settings.base_url == "http://localhost:11434"
    assert settings.model == "llama3.2:3b"
    assert settings.timeout_seconds == 60.0
    assert settings.temperature == 0.1
    assert settings.keep_alive == "5m"


def test_ollama_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify settings respect environment variable overrides."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.100:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:1b")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "30.0")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.3")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "10m")

    settings = get_ollama_settings()
    assert settings.base_url == "http://192.168.1.100:11434"
    assert settings.model == "llama3.2:1b"
    assert settings.timeout_seconds == 30.0
    assert settings.temperature == 0.3
    assert settings.keep_alive == "10m"


async def test_ollama_service_check_health_success() -> None:
    """Verify check_health returns True when Ollama client succeeds."""
    mock_client = AsyncMock()
    mock_client.list.return_value = MagicMock(models=[])
    service = OllamaService(client=mock_client)

    assert await service.check_health() is True


async def test_ollama_service_check_health_failure() -> None:
    """Verify check_health returns False when Ollama client fails."""
    mock_client = AsyncMock()
    mock_client.list.side_effect = httpx.ConnectError("Connection refused")
    service = OllamaService(client=mock_client)

    assert await service.check_health() is False


async def test_ollama_service_ensure_model_available_success() -> None:
    """Verify ensure_model_available succeeds when model is present."""
    mock_client = AsyncMock()
    mock_model = MagicMock()
    mock_model.model = "llama3.2:3b"
    mock_client.list.return_value = MagicMock(models=[mock_model])

    service = OllamaService(
        settings=OllamaSettings(model="llama3.2:3b"),
        client=mock_client,
    )
    # Should not raise
    await service.ensure_model_available()


async def test_ollama_service_ensure_model_available_not_found() -> None:
    """Verify ensure_model_available raises OllamaModelNotFoundError when model is missing."""
    mock_client = AsyncMock()
    mock_model = MagicMock()
    mock_model.model = "other-model:latest"
    mock_client.list.return_value = MagicMock(models=[mock_model])

    service = OllamaService(
        settings=OllamaSettings(model="llama3.2:3b"),
        client=mock_client,
    )
    with pytest.raises(OllamaModelNotFoundError) as exc_info:
        await service.ensure_model_available()

    assert "not installed locally" in str(exc_info.value)


async def test_ollama_service_unavailable_error() -> None:
    """Verify connection refusal maps cleanly to OllamaServiceUnavailableError."""
    mock_client = AsyncMock()
    mock_client.chat.side_effect = httpx.ConnectError("Connection refused")

    service = OllamaService(client=mock_client)
    with pytest.raises(OllamaServiceUnavailableError) as exc_info:
        await service.chat(messages=[{"role": "user", "content": "hi"}])

    assert "Could not connect to Ollama daemon" in str(exc_info.value)


async def test_ollama_service_timeout_error() -> None:
    """Verify timeout maps cleanly to OllamaTimeoutError."""
    mock_client = AsyncMock()
    mock_client.chat.side_effect = httpx.ReadTimeout("Request timed out")

    service = OllamaService(client=mock_client)
    with pytest.raises(OllamaTimeoutError) as exc_info:
        await service.chat(messages=[{"role": "user", "content": "hi"}])

    assert "timed out" in str(exc_info.value)


async def test_ollama_service_model_not_found_on_chat() -> None:
    """Verify 404 ResponseError maps to OllamaModelNotFoundError."""
    mock_client = AsyncMock()
    mock_client.chat.side_effect = ResponseError(
        "model 'llama3.2:3b' not found", status_code=404
    )

    service = OllamaService(client=mock_client)
    with pytest.raises(OllamaModelNotFoundError) as exc_info:
        await service.chat(messages=[{"role": "user", "content": "hi"}])

    assert "not found in Ollama" in str(exc_info.value)


async def test_ollama_service_generic_inference_error() -> None:
    """Verify other ResponseError maps to OllamaInferenceError."""
    mock_client = AsyncMock()
    mock_client.chat.side_effect = ResponseError("CUDA out of memory", status_code=500)

    service = OllamaService(client=mock_client)
    with pytest.raises(OllamaInferenceError) as exc_info:
        await service.chat(messages=[{"role": "user", "content": "hi"}])

    assert "Ollama inference error" in str(exc_info.value)
