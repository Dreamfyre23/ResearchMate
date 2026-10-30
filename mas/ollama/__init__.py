"""Ollama integration package for local AI models (Phase 9)."""

from mas.ollama.client import OllamaService
from mas.ollama.exceptions import (
    OllamaError,
    OllamaInferenceError,
    OllamaModelNotFoundError,
    OllamaServiceUnavailableError,
    OllamaTimeoutError,
)

__all__ = [
    "OllamaError",
    "OllamaInferenceError",
    "OllamaModelNotFoundError",
    "OllamaService",
    "OllamaServiceUnavailableError",
    "OllamaTimeoutError",
]
