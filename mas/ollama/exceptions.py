"""Exceptions for Ollama model interaction and inference (Phase 9)."""


class OllamaError(Exception):
    """Base exception for all Ollama integration errors."""


class OllamaServiceUnavailableError(OllamaError):
    """Raised when the Ollama HTTP daemon is unreachable, offline, or refusing connections."""


class OllamaModelNotFoundError(OllamaError):
    """Raised when the requested Ollama model is not found or not pulled."""


class OllamaTimeoutError(OllamaError):
    """Raised when an inference or communication request times out."""


class OllamaInferenceError(OllamaError):
    """Raised when Ollama inference produces an invalid or unparseable response."""
