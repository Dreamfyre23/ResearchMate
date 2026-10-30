"""Ollama service abstraction for local LLM inference (Phase 9).

Provides connection management, health checks, model verification, and chat completions
supporting tool calling using the official Python ollama SDK (DEC-009, DEC-025).
"""

import asyncio
import logging
from typing import Any

import httpx
import ollama
from ollama._types import ResponseError

from mas.config.settings import OllamaSettings, get_ollama_settings
from mas.ollama.exceptions import (
    OllamaInferenceError,
    OllamaModelNotFoundError,
    OllamaServiceUnavailableError,
    OllamaTimeoutError,
)

logger = logging.getLogger(__name__)


def _is_connection_error(exc: BaseException) -> bool:
    """Check if an exception is caused by network connection failure to Ollama."""
    name = type(exc).__name__.lower()
    if isinstance(exc, (httpx.ConnectError, ConnectionRefusedError, OSError)):
        return True
    return "connect" in name or "connectionrefused" in name


def _is_timeout_error(exc: BaseException) -> bool:
    """Check if an exception is caused by a request timeout."""
    name = type(exc).__name__.lower()
    if isinstance(exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return True
    return "timeout" in name


class OllamaService:
    """Service wrapper for interacting with the local Ollama daemon."""

    def __init__(
        self,
        settings: OllamaSettings | None = None,
        client: ollama.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_ollama_settings()
        self._client = client or ollama.AsyncClient(
            host=self._settings.base_url,
            timeout=self._settings.timeout_seconds,
        )

    @property
    def model_name(self) -> str:
        """Return the configured model identifier."""
        return self._settings.model

    @property
    def base_url(self) -> str:
        """Return the configured base URL."""
        return self._settings.base_url

    async def check_health(self) -> bool:
        """Verify the Ollama service is reachable and responding."""
        try:
            await self._client.list()
            return True
        except (BaseExceptionGroup, Exception) as exc:  # noqa: BLE001
            logger.debug("Ollama health check failed: %s", exc)
            return False

    async def list_models(self) -> list[str]:
        """Retrieve the list of locally available model names."""
        try:
            res = await self._client.list()
            names = []
            for m in res.models:
                name = getattr(m, "model", None) or getattr(m, "name", None)
                if name:
                    names.append(name)
            return names
        except BaseException as exc:
            if _is_connection_error(exc):
                raise OllamaServiceUnavailableError(
                    f"Could not connect to Ollama daemon at {self._settings.base_url}: {exc}"
                ) from exc
            if _is_timeout_error(exc):
                raise OllamaTimeoutError(
                    f"Ollama list request timed out after {self._settings.timeout_seconds}s"
                ) from exc
            raise OllamaInferenceError(
                f"Failed to list models from Ollama: {exc}"
            ) from exc

    async def ensure_model_available(self) -> bool:
        """Verify the configured model is installed locally.

        Does not download or pull models automatically (per project rules).

        Returns:
            True if the model is installed locally.

        Raises:
            OllamaModelNotFoundError: If the configured model is not found.
        """
        available = await self.list_models()
        target = self._settings.model.lower()

        # Handle tag variants (e.g. llama3.2:3b vs llama3.2:3b:latest)
        found = any(
            m.lower() == target
            or m.lower().startswith(f"{target}:")
            or target.startswith(f"{m.lower()}:")
            for m in available
        )
        if not found:
            raise OllamaModelNotFoundError(
                f"Configured Ollama model '{self._settings.model}' is not installed locally. "
                f"Available models: {available}. "
                "Per project rules, coding agents must not download models automatically."
            )
        return True

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> Any:
        """Send chat messages and optional tool specifications to the local Ollama model.

        Args:
            messages: List of message mappings (role, content, etc.).
            tools: Optional list of tool definitions in function format.
            temperature: Optional override for sampling temperature.

        Returns:
            ChatResponse from Ollama SDK containing message and tool_calls.
        """
        options: dict[str, Any] = {
            "temperature": temperature
            if temperature is not None
            else self._settings.temperature
        }

        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "options": options,
            "keep_alive": self._settings.keep_alive,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            return await self._client.chat(**kwargs)
        except BaseException as exc:
            if isinstance(exc, ResponseError):
                if (
                    getattr(exc, "status_code", None) == 404
                    or "not found" in str(exc).lower()
                ):
                    raise OllamaModelNotFoundError(
                        f"Model '{self._settings.model}' not found in Ollama: {exc}"
                    ) from exc
                raise OllamaInferenceError(
                    f"Ollama inference error ({exc.status_code}): {exc}"
                ) from exc
            if _is_connection_error(exc):
                raise OllamaServiceUnavailableError(
                    f"Could not connect to Ollama daemon at {self._settings.base_url}: {exc}"
                ) from exc
            if _is_timeout_error(exc):
                raise OllamaTimeoutError(
                    f"Ollama inference timed out after {self._settings.timeout_seconds}s: {exc}"
                ) from exc
            raise OllamaInferenceError(
                f"Unexpected error during Ollama inference: {exc}"
            ) from exc
