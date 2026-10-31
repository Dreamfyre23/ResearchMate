"""Configuration settings for Ollama integration and local AI agents (Phase 9)."""

from typing import Any

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
        default="gemini-3.5-flash-lite",
        validation_alias="GEMINI_MODEL",
        description="Gemini model identifier for central orchestrator (legacy/fallback)",
    )
    primary_model: str | None = Field(
        default=None,
        validation_alias="GEMINI_PRIMARY_MODEL",
        description="Primary Gemini model identifier (takes precedence over GEMINI_MODEL)",
    )
    fallback_models: str | None = Field(
        default=None,
        validation_alias="GEMINI_FALLBACK_MODELS",
        description="Comma-separated list of fallback Gemini models in priority order",
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
    model_retry_attempts: int = Field(
        default=1,
        validation_alias="GEMINI_MODEL_RETRY_ATTEMPTS",
        description="Number of retries per model for transient errors (503, timeouts) before switching",
    )
    model_retry_delay: float = Field(
        default=0.5,
        validation_alias="GEMINI_MODEL_RETRY_DELAY",
        description="Delay in seconds between retries for transient errors",
    )

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        if "model" in values and "primary_model" not in values:
            self.primary_model = values["model"]
        elif self.primary_model and "model" not in values:
            self.model = self.primary_model

    @property
    def model_candidates(self) -> list[str]:
        """Return the deduplicated, ordered list of model candidates.

        Priority order:
        1. primary_model (or model fallback)
        2. fallback_models (comma-separated)

        Preserves priority order, trims whitespace, removes empty and duplicate entries.
        """
        raw_candidates: list[str] = []
        first_model = (self.primary_model or self.model or "").strip()
        if first_model:
            raw_candidates.append(first_model)

        if self.fallback_models:
            for item in self.fallback_models.split(","):
                cleaned = item.strip()
                if cleaned:
                    raw_candidates.append(cleaned)

        seen: set[str] = set()
        candidates: list[str] = []
        for m in raw_candidates:
            if m not in seen:
                seen.add(m)
                candidates.append(m)

        if not candidates:
            candidates = ["gemini-3.5-flash-lite"]
        return candidates

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
