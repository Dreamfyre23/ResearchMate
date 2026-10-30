"""Configuration settings for Ollama integration and local AI agents (Phase 9)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaSettings(BaseSettings):
    """Configuration settings for connecting to the local Ollama runtime."""

    base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
        description="Base URL for the locally running Ollama HTTP service",
    )
    model: str = Field(
        default="llama3.2:3b",
        validation_alias="OLLAMA_MODEL",
        description="Local Ollama model identifier to use across agents (DEC-009)",
    )
    timeout_seconds: float = Field(
        default=60.0,
        validation_alias="OLLAMA_TIMEOUT_SECONDS",
        description="Timeout in seconds for model inference requests",
    )
    temperature: float = Field(
        default=0.1,
        validation_alias="OLLAMA_TEMPERATURE",
        description="Sampling temperature for deterministic tool calling and structured reasoning",
    )
    keep_alive: str = Field(
        default="5m",
        validation_alias="OLLAMA_KEEP_ALIVE",
        description="How long to keep the single model instance in memory (8GB RAM optimization)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


class AgentSettings(BaseSettings):
    """Configuration settings governing agent loop execution and limits."""

    max_iterations: int = Field(
        default=10,
        validation_alias="AGENT_MAX_ITERATIONS",
        description="Maximum iterations per request to prevent uncontrolled tool-call loops",
    )
    log_level: str = Field(
        default="info",
        validation_alias="AGENT_LOG_LEVEL",
        description="Logging level for MAS agents",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


class GeminiSettings(BaseSettings):
    """Configuration settings for connecting to Google Gemini API (Phase 10)."""

    api_key: str | None = Field(
        default=None,
        validation_alias="GOOGLE_API_KEY",
        description="Google Gemini API key from environment",
    )
    model: str = Field(
        default="gemini-flash-latest",
        validation_alias="GEMINI_MODEL",
        description="Gemini model identifier for central orchestrator (DEC-008)",
    )
    timeout_seconds: float = Field(
        default=60.0,
        validation_alias="GEMINI_TIMEOUT_SECONDS",
        description="Timeout in seconds for Gemini API requests",
    )
    temperature: float = Field(
        default=0.2,
        validation_alias="GEMINI_TEMPERATURE",
        description="Sampling temperature for orchestrator planning and response synthesis",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


class OrchestratorSettings(BaseSettings):
    """Configuration settings governing central orchestrator delegation and coordination."""

    max_delegation_steps: int = Field(
        default=5,
        validation_alias="ORCHESTRATOR_MAX_STEPS",
        description="Maximum number of agent delegation steps per request to prevent unbounded loops",
    )
    agent_timeout_seconds: float = Field(
        default=120.0,
        validation_alias="ORCHESTRATOR_AGENT_TIMEOUT",
        description="Maximum seconds to wait for a delegated local agent run before timing out",
    )
    log_level: str = Field(
        default="info",
        validation_alias="ORCHESTRATOR_LOG_LEVEL",
        description="Logging level for central orchestrator",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


def get_ollama_settings() -> OllamaSettings:
    """Return an instance of OllamaSettings loaded from environment."""
    return OllamaSettings()


def get_agent_settings() -> AgentSettings:
    """Return an instance of AgentSettings loaded from environment."""
    return AgentSettings()


def get_gemini_settings() -> GeminiSettings:
    """Return an instance of GeminiSettings loaded from environment."""
    return GeminiSettings()


def get_orchestrator_settings() -> OrchestratorSettings:
    """Return an instance of OrchestratorSettings loaded from environment."""
    return OrchestratorSettings()
