"""Google Gemini API service for Research Agent and Task Agent (DEC-033).

Provides function-calling inference for sub-agents using the official
google-genai SDK, featuring multi-model fallback and health tracking.

Design choices:
- Shares GOOGLE_API_KEY with the orchestrator.
- Uses AGENT_GEMINI_PRIMARY_MODEL / AGENT_GEMINI_FALLBACK_MODELS for resilient multi-model fallback.
- In-memory AgentModelHealthTracker tracks cooldowns for exhausted or failing models.
- Wraps errors in AgentGeminiError subclasses so BaseAgent can handle them
  without depending on orchestrator exceptions.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from google import genai
from google.genai import errors, types

from mas.config.settings import AgentGeminiSettings, get_agent_gemini_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AgentGeminiError(Exception):
    """Base exception for Gemini agent inference failures."""


class AgentGeminiConfigurationError(AgentGeminiError):
    """Raised when the API key or model configuration is missing or invalid."""


class AgentGeminiRateLimitError(AgentGeminiError):
    """Raised on 429 / RESOURCE_EXHAUSTED responses."""


class AgentGeminiDailyQuotaExhaustedError(AgentGeminiRateLimitError):
    """Raised when the daily request quota for an agent Gemini model is exhausted."""


class AgentGeminiServiceUnavailableError(AgentGeminiError):
    """Raised on 503 or transient server errors."""


class AgentGeminiTimeoutError(AgentGeminiError):
    """Raised when the request exceeds the configured timeout."""


class AgentGeminiAPIError(AgentGeminiError):
    """Raised for other Gemini API failures."""


# ---------------------------------------------------------------------------
# Failure Categorization & Health Tracker
# ---------------------------------------------------------------------------


class AgentGeminiFailureCategory(str, Enum):
    """Classification categories for Gemini API failures to govern fallback behavior."""

    DAILY_QUOTA_EXHAUSTED = "DAILY_QUOTA_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    OVERLOADED_503 = "OVERLOADED_503"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR_5XX = "SERVER_ERROR_5XX"
    NOT_FOUND_404 = "NOT_FOUND_404"
    INVALID_REQUEST_400 = "INVALID_REQUEST_400"
    AUTH_ERROR_401_403 = "AUTH_ERROR_401_403"
    UNKNOWN = "UNKNOWN"


@dataclass
class AgentModelFailureRecord:
    """In-memory record tracking failure state and cooldown for an agent Gemini model."""

    model_name: str
    failure_category: AgentGeminiFailureCategory
    failed_at: float
    retry_after: float
    error_message: str


class AgentModelHealthTracker:
    """Lightweight in-memory tracker avoiding calls to known exhausted or failing models."""

    def __init__(self) -> None:
        self._failures: dict[str, AgentModelFailureRecord] = {}

    def record_failure(
        self,
        model_name: str,
        category: AgentGeminiFailureCategory,
        retry_after: float | None = None,
        error_message: str = "",
    ) -> None:
        """Record a failure event with an appropriate cooldown window."""
        now = time.monotonic()
        if retry_after is None:
            if category == AgentGeminiFailureCategory.DAILY_QUOTA_EXHAUSTED:
                retry_after = 86400.0  # 24 hours for daily quota
            elif category == AgentGeminiFailureCategory.NOT_FOUND_404:
                retry_after = 86400.0  # 24 hours for obsolete/nonexistent models
            elif category == AgentGeminiFailureCategory.RATE_LIMITED:
                retry_after = 60.0  # 60s for burst rate limit
            else:
                retry_after = 30.0  # 30s default cooldown

        self._failures[model_name] = AgentModelFailureRecord(
            model_name=model_name,
            failure_category=category,
            failed_at=now,
            retry_after=retry_after,
            error_message=error_message,
        )

    def record_success(self, model_name: str) -> None:
        """Clear any failure record when a model call succeeds."""
        self._failures.pop(model_name, None)

    def is_model_available(self, model_name: str) -> bool:
        """Check whether a model is available to receive requests (not in cooldown)."""
        record = self._failures.get(model_name)
        if not record:
            return True
        now = time.monotonic()
        if now - record.failed_at >= record.retry_after:
            del self._failures[model_name]
            return True
        return False

    def get_failure_record(self, model_name: str) -> AgentModelFailureRecord | None:
        """Retrieve failure details for a given model if recorded."""
        return self._failures.get(model_name)

    def clear(self) -> None:
        """Clear all failure records."""
        self._failures.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact_key(message: str, api_key: str | None) -> str:
    """Remove API key from error messages before logging."""
    if not message:
        return ""
    result = message
    if api_key:
        result = result.replace(api_key, "[REDACTED_API_KEY]")
    result = re.sub(r"AIzaSy[A-Za-z0-9_-]{30,40}", "[REDACTED_API_KEY]", result)
    return result


def _extract_retry_and_quota(
    details: Any, message: str = ""
) -> tuple[float | None, bool]:
    """Inspect error details and message for retry delay and daily quota signals."""
    msg = (message or "").lower()
    details_str = str(details).lower() if details else ""
    retry_delay: float | None = None
    is_daily = False

    daily_signals = [
        "perday",
        "per day",
        "daily",
        "free_tier",
        "freetier",
        "generaterequestsperday",
        "day",
    ]
    if any(sig in msg or sig in details_str for sig in daily_signals):
        is_daily = True

    if isinstance(details, dict):
        det_list = details.get("error", {}).get("details", []) or details.get(
            "details", []
        )
    elif isinstance(details, list):
        det_list = details
    else:
        det_list = []

    for item in det_list:
        if isinstance(item, dict):
            if "retryDelay" in item:
                rd = item["retryDelay"]
                if isinstance(rd, str) and rd.endswith("s"):
                    rd = rd[:-1]
                try:
                    retry_delay = float(rd)
                except (ValueError, TypeError):
                    pass
            for v in item.get("violations", []):
                v_str = str(v).lower()
                if any(sig in v_str for sig in daily_signals):
                    is_daily = True

    if retry_delay is not None and retry_delay > 60:
        is_daily = True

    return retry_delay, is_daily


def classify_agent_gemini_error(
    exc: Exception, api_key: str | None = None
) -> tuple[AgentGeminiFailureCategory, float | None, str]:
    """Classify an exception from Google Gemini API into category, retry delay, and safe message."""
    safe_msg = _redact_key(str(exc), api_key)

    if isinstance(exc, (TimeoutError, AgentGeminiTimeoutError)):
        return AgentGeminiFailureCategory.TIMEOUT, None, safe_msg

    if isinstance(exc, AgentGeminiDailyQuotaExhaustedError):
        return AgentGeminiFailureCategory.DAILY_QUOTA_EXHAUSTED, None, safe_msg

    if isinstance(exc, AgentGeminiRateLimitError):
        return AgentGeminiFailureCategory.RATE_LIMITED, None, safe_msg

    if isinstance(exc, AgentGeminiConfigurationError):
        return AgentGeminiFailureCategory.AUTH_ERROR_401_403, None, safe_msg

    if isinstance(exc, AgentGeminiServiceUnavailableError):
        return AgentGeminiFailureCategory.OVERLOADED_503, None, safe_msg

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", None) or "").upper()
        message = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None)

        retry_delay, is_daily = _extract_retry_and_quota(details, message)

        if code == 429 or status == "RESOURCE_EXHAUSTED":
            if is_daily or (retry_delay is not None and retry_delay > 60):
                return (
                    AgentGeminiFailureCategory.DAILY_QUOTA_EXHAUSTED,
                    retry_delay,
                    safe_msg,
                )
            return (
                AgentGeminiFailureCategory.RATE_LIMITED,
                retry_delay or 60.0,
                safe_msg,
            )

        if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return AgentGeminiFailureCategory.AUTH_ERROR_401_403, None, safe_msg

        if code == 400 or status == "INVALID_ARGUMENT":
            return AgentGeminiFailureCategory.INVALID_REQUEST_400, None, safe_msg

        if code == 404 or status == "NOT_FOUND":
            return AgentGeminiFailureCategory.NOT_FOUND_404, None, safe_msg

        if code == 503 or status == "UNAVAILABLE":
            return AgentGeminiFailureCategory.OVERLOADED_503, retry_delay, safe_msg

        if (code is not None and 500 <= code < 600) or status == "INTERNAL":
            return AgentGeminiFailureCategory.SERVER_ERROR_5XX, retry_delay, safe_msg

        return AgentGeminiFailureCategory.UNKNOWN, None, safe_msg

    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return AgentGeminiFailureCategory.SERVER_ERROR_5XX, None, safe_msg

    return AgentGeminiFailureCategory.UNKNOWN, None, safe_msg


def _descriptor_to_gemini_tool(
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
) -> types.Tool:
    """Convert an MCP tool descriptor into a google-genai Tool object."""
    properties: dict[str, Any] = {}

    raw_props = input_schema.get("properties", {})
    for prop_name, prop_schema in raw_props.items():
        prop_type = prop_schema.get("type", "string")
        type_map = {
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }
        gemini_type = type_map.get(prop_type, "STRING")
        prop_def: dict[str, Any] = {
            "type": gemini_type,
            "description": prop_schema.get("description", ""),
        }
        if "enum" in prop_schema:
            prop_def["enum"] = prop_schema["enum"]
        if prop_type == "array" and "items" in prop_schema:
            items = prop_schema["items"]
            item_type = type_map.get(items.get("type", "string"), "STRING")
            prop_def["items"] = {"type": item_type}
        properties[prop_name] = prop_def

    required = list(input_schema.get("required", []))

    func_decl = types.FunctionDeclaration(
        name=tool_name,
        description=tool_description,
        parameters=types.Schema(
            type="OBJECT",
            properties={k: types.Schema(**v) for k, v in properties.items()},
            required=required if required else None,
        ),
    )
    return types.Tool(function_declarations=[func_decl])


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class AgentGeminiService:
    """Gemini API wrapper for sub-agent function-calling with multi-model fallback."""

    def __init__(
        self,
        settings: AgentGeminiSettings | None = None,
        client: genai.Client | None = None,
        tracker: AgentModelHealthTracker | None = None,
    ) -> None:
        self._settings = settings or get_agent_gemini_settings()
        self._client = client
        self.tracker = tracker or AgentModelHealthTracker()

    @property
    def model_name(self) -> str:
        """Return the primary configured agent model identifier."""
        candidates = self._settings.model_candidates
        return candidates[0] if candidates else self._settings.model

    @property
    def client(self) -> genai.Client:
        """Lazy-initialize and cache the google-genai Client."""
        if self._client is None:
            api_key = self._settings.api_key
            if not api_key or api_key == "replace_with_your_api_key":
                raise AgentGeminiConfigurationError(
                    "GOOGLE_API_KEY is not configured. "
                    "Set it in your .env file to enable agent inference."
                )
            self._client = genai.Client(api_key=api_key)
        return self._client

    async def _execute_with_model_fallback(
        self,
        operation_name: str,
        call_fn: Callable[[str], Awaitable[T]],
    ) -> tuple[T, str]:
        """Execute call_fn across candidate models with automatic retry and fallback."""
        candidates = self._settings.model_candidates
        if not candidates:
            candidates = ["gemini-3.5-flash-lite"]

        available_models = [m for m in candidates if self.tracker.is_model_available(m)]
        for m in candidates:
            if m not in available_models:
                logger.info("Agent model %s is in cooldown; skipping.", m)

        if not available_models:
            logger.warning(
                "All agent Gemini candidate models are currently in cooldown or daily quota exhausted."
            )
            first_record = self.tracker.get_failure_record(candidates[0])
            if first_record:
                if (
                    first_record.failure_category
                    == AgentGeminiFailureCategory.NOT_FOUND_404
                ):
                    raise AgentGeminiConfigurationError(
                        f"Agent Gemini model not found: {first_record.error_message}"
                    )
                if (
                    first_record.failure_category
                    == AgentGeminiFailureCategory.DAILY_QUOTA_EXHAUSTED
                ):
                    raise AgentGeminiDailyQuotaExhaustedError(
                        f"Agent Gemini daily quota exhausted: {first_record.error_message}"
                    )
                if (
                    first_record.failure_category
                    == AgentGeminiFailureCategory.RATE_LIMITED
                ):
                    raise AgentGeminiRateLimitError(
                        f"Agent Gemini API rate limit exceeded: {first_record.error_message}"
                    )
                if first_record.failure_category == AgentGeminiFailureCategory.TIMEOUT:
                    raise AgentGeminiTimeoutError("Agent Gemini request timed out.")
                if first_record.failure_category in (
                    AgentGeminiFailureCategory.OVERLOADED_503,
                    AgentGeminiFailureCategory.SERVER_ERROR_5XX,
                ):
                    raise AgentGeminiServiceUnavailableError(
                        f"Agent Gemini API service unavailable: {first_record.error_message}"
                    )
            raise AgentGeminiDailyQuotaExhaustedError(
                "All agent Gemini candidate models are currently in cooldown or daily quota exhausted."
            )

        last_error: Exception | None = None
        last_category = AgentGeminiFailureCategory.UNKNOWN
        last_safe_msg = "Unknown error"
        primary_model = candidates[0]

        for model_name in available_models:
            is_primary = model_name == primary_model
            if is_primary:
                logger.info("Agent using primary model: %s", model_name)
            else:
                logger.info("Agent switching to fallback model: %s", model_name)

            max_attempts = 1 + max(0, self._settings.model_retry_attempts)

            for attempt in range(max_attempts):
                try:
                    result = await call_fn(model_name)
                    self.tracker.record_success(model_name)
                    if not is_primary:
                        logger.info("Agent fallback model succeeded: %s", model_name)
                    return result, model_name

                except Exception as exc:
                    category, retry_delay, safe_msg = classify_agent_gemini_error(
                        exc, self._settings.api_key
                    )
                    last_error = exc
                    last_category = category
                    last_safe_msg = safe_msg

                    # Non-switchable errors: terminate traversal immediately
                    if category == AgentGeminiFailureCategory.AUTH_ERROR_401_403:
                        logger.error(
                            "Authentication error with Gemini API for agent: %s",
                            safe_msg,
                        )
                        raise AgentGeminiConfigurationError(
                            f"Gemini authentication failed: {safe_msg}"
                        ) from exc

                    if category == AgentGeminiFailureCategory.INVALID_REQUEST_400:
                        logger.error(
                            "Invalid request to Gemini API for agent (400): %s",
                            safe_msg,
                        )
                        raise AgentGeminiAPIError(
                            f"Gemini API invalid request: {safe_msg}"
                        ) from exc

                    # Check for bounded retry on transient issues
                    is_retriable = category in (
                        AgentGeminiFailureCategory.OVERLOADED_503,
                        AgentGeminiFailureCategory.TIMEOUT,
                        AgentGeminiFailureCategory.SERVER_ERROR_5XX,
                    )

                    if is_retriable and attempt + 1 < max_attempts:
                        logger.warning(
                            "Transient error (%s) on agent model %s; retrying attempt %d/%d in %.1fs...",
                            category.value,
                            model_name,
                            attempt + 1,
                            max_attempts,
                            self._settings.model_retry_delay,
                        )
                        if self._settings.model_retry_delay > 0:
                            await asyncio.sleep(self._settings.model_retry_delay)
                        continue

                    # Record failure on tracker and move to next model
                    self.tracker.record_failure(
                        model_name=model_name,
                        category=category,
                        retry_after=retry_delay,
                        error_message=safe_msg,
                    )

                    if is_primary:
                        logger.warning(
                            "Primary agent model %s failed (%s); evaluating fallbacks...",
                            model_name,
                            category.value,
                        )
                    else:
                        logger.warning(
                            "Fallback agent model %s failed (%s); evaluating next candidate...",
                            model_name,
                            category.value,
                        )

                    break

        # All available models failed
        logger.warning(
            "All agent Gemini candidate models failed for %s.",
            operation_name,
        )

        if last_category == AgentGeminiFailureCategory.DAILY_QUOTA_EXHAUSTED:
            raise AgentGeminiDailyQuotaExhaustedError(
                f"Agent Gemini daily quota exhausted: {last_safe_msg}"
            ) from last_error
        elif last_category == AgentGeminiFailureCategory.RATE_LIMITED:
            raise AgentGeminiRateLimitError(
                f"Agent Gemini API rate limit exceeded: {last_safe_msg}"
            ) from last_error
        elif last_category == AgentGeminiFailureCategory.TIMEOUT:
            raise AgentGeminiTimeoutError(
                "Agent Gemini request timed out."
            ) from last_error
        elif last_category in (
            AgentGeminiFailureCategory.OVERLOADED_503,
            AgentGeminiFailureCategory.SERVER_ERROR_5XX,
        ):
            raise AgentGeminiServiceUnavailableError(
                f"Agent Gemini API service unavailable: {last_safe_msg}"
            ) from last_error
        elif last_category == AgentGeminiFailureCategory.NOT_FOUND_404:
            raise AgentGeminiConfigurationError(
                f"Agent Gemini model not found: {last_safe_msg}"
            ) from last_error
        else:
            raise AgentGeminiAPIError(
                f"Agent Gemini API error: {last_safe_msg}"
            ) from last_error

    async def chat(
        self,
        system_prompt: str,
        messages: list[types.Content],
        tools: list[types.Tool] | None = None,
    ) -> Any:
        """Send a conversation turn to Gemini with multi-model fallback.

        Args:
            system_prompt: Agent system instructions (passed as system_instruction).
            messages: Accumulated conversation as a list of Content objects.
            tools: Optional list of Gemini Tool objects for function calling.

        Returns:
            GenerateContentResponse from the google-genai SDK.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._settings.temperature,
            tools=tools if tools else None,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="AUTO",
                )
            )
            if tools
            else None,
        )

        async def _do_generate(model_name: str) -> Any:
            return await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=model_name,
                    contents=messages,
                    config=config,
                ),
                timeout=self._settings.timeout_seconds,
            )

        response, _ = await self._execute_with_model_fallback(
            "agent_chat", _do_generate
        )
        return response
