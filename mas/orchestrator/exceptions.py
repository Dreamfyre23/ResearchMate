"""Exception hierarchy for central Gemini-powered orchestrator (Phase 10)."""


class OrchestratorError(Exception):
    """Base exception for all orchestrator-related failures."""


class GeminiError(OrchestratorError):
    """Base exception for Google Gemini API integration failures."""


class GeminiConfigurationError(GeminiError):
    """Raised when Gemini configuration (e.g., API key) is missing or invalid."""


class GeminiServiceUnavailableError(GeminiError):
    """Raised when the Gemini API service is unreachable or network connection fails."""


class GeminiTimeoutError(GeminiError):
    """Raised when a request to Gemini API exceeds the configured timeout."""


class GeminiRateLimitError(GeminiError):
    """Raised when Gemini API returns 429 / resource exhausted / rate limit exceeded."""


class GeminiDailyQuotaExhaustedError(GeminiRateLimitError):
    """Raised when the daily request quota for a Gemini model is exhausted."""


class GeminiAPIError(GeminiError):
    """Raised when Gemini API encounters a server or inference error."""


class AgentExecutionError(OrchestratorError):
    """Raised when an error occurs during execution of a delegated agent."""


class AgentTimeoutError(OrchestratorError):
    """Raised when a delegated agent execution exceeds the allowable timeout."""


class DelegationLimitExceededError(OrchestratorError):
    """Raised when a delegation plan attempts to exceed maximum allowed delegation steps."""
