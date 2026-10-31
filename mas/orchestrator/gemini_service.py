"""Google Gemini API service integration for central orchestrator (Phase 10).

Interacts with the Google Gemini API using the official google-genai SDK for request
understanding, agent delegation planning, and response synthesis with multi-model fallback.
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

from mas.config.settings import GeminiSettings, get_gemini_settings
from mas.orchestrator.exceptions import (
    GeminiAPIError,
    GeminiConfigurationError,
    GeminiDailyQuotaExhaustedError,
    GeminiRateLimitError,
    GeminiServiceUnavailableError,
    GeminiTimeoutError,
)
from mas.orchestrator.models import (
    AgentTarget,
    DelegationPlan,
    DelegationResult,
    DelegationTask,
    ExecutionMode,
)
from mas.orchestrator.prompts import (
    ORCHESTRATOR_PLANNING_SYSTEM_PROMPT,
    ORCHESTRATOR_SYNTHESIS_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class GeminiFailureCategory(str, Enum):
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
class ModelFailureRecord:
    """In-memory record tracking failure state and cooldown for a Gemini model."""

    model_name: str
    failure_category: GeminiFailureCategory
    failed_at: float
    retry_after: float
    error_message: str


class ModelHealthTracker:
    """Lightweight in-memory tracker avoiding calls to known exhausted or failing models."""

    def __init__(self) -> None:
        self._failures: dict[str, ModelFailureRecord] = {}

    def record_failure(
        self,
        model_name: str,
        category: GeminiFailureCategory,
        retry_after: float | None = None,
        error_message: str = "",
    ) -> None:
        """Record a failure event with an appropriate cooldown window."""
        now = time.monotonic()
        if retry_after is None:
            if category == GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED:
                retry_after = 86400.0  # 24 hours for daily quota
            elif category == GeminiFailureCategory.NOT_FOUND_404:
                retry_after = 86400.0  # 24 hours for obsolete/nonexistent models
            elif category == GeminiFailureCategory.RATE_LIMITED:
                retry_after = 60.0  # 60s for burst/RPM rate limit
            else:
                retry_after = 30.0  # 30s default cooldown

        self._failures[model_name] = ModelFailureRecord(
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

    def get_failure_record(self, model_name: str) -> ModelFailureRecord | None:
        """Retrieve failure details for a given model if recorded."""
        return self._failures.get(model_name)

    def clear(self) -> None:
        """Clear all failure records."""
        self._failures.clear()


def _redact_secrets(message: str, api_key: str | None) -> str:
    """Ensure API key is never exposed in error messages or logs."""
    if not message:
        return ""
    result = message
    if api_key:
        result = result.replace(api_key, "[REDACTED_API_KEY]")
    # Defense-in-depth: redact standard Google API key patterns (AIzaSy...)
    result = re.sub(r"AIzaSy[A-Za-z0-9_-]{30,40}", "[REDACTED_API_KEY]", result)
    return result


def _clean_json_markdown(raw_text: str) -> str:
    """Strip markdown code fence backticks from LLM output if present."""
    text = raw_text.strip()
    pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return text


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


def classify_gemini_error(
    exc: Exception, api_key: str | None = None
) -> tuple[GeminiFailureCategory, float | None, str]:
    """Classify an exception from Google Gemini API into category, retry delay, and safe message.

    Returns:
        (category, retry_delay_seconds, safe_error_message)
    """
    safe_msg = _redact_secrets(str(exc), api_key)

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, GeminiTimeoutError)):
        return GeminiFailureCategory.TIMEOUT, None, safe_msg

    if isinstance(exc, GeminiDailyQuotaExhaustedError):
        return GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED, None, safe_msg

    if isinstance(exc, GeminiRateLimitError):
        return GeminiFailureCategory.RATE_LIMITED, None, safe_msg

    if isinstance(exc, GeminiConfigurationError):
        return GeminiFailureCategory.AUTH_ERROR_401_403, None, safe_msg

    if isinstance(exc, GeminiServiceUnavailableError):
        return GeminiFailureCategory.OVERLOADED_503, None, safe_msg

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", None) or "").upper()
        message = getattr(exc, "message", None) or str(exc)
        details = getattr(exc, "details", None)

        retry_delay, is_daily = _extract_retry_and_quota(details, message)

        if code == 429 or status == "RESOURCE_EXHAUSTED":
            if is_daily or (retry_delay is not None and retry_delay > 60):
                return (
                    GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED,
                    retry_delay,
                    safe_msg,
                )
            return GeminiFailureCategory.RATE_LIMITED, retry_delay or 60.0, safe_msg

        if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return GeminiFailureCategory.AUTH_ERROR_401_403, None, safe_msg

        if code == 400 or status == "INVALID_ARGUMENT":
            return GeminiFailureCategory.INVALID_REQUEST_400, None, safe_msg

        if code == 404 or status == "NOT_FOUND":
            return GeminiFailureCategory.NOT_FOUND_404, None, safe_msg

        if code == 503 or status == "UNAVAILABLE":
            return GeminiFailureCategory.OVERLOADED_503, retry_delay, safe_msg

        if (code is not None and 500 <= code < 600) or status == "INTERNAL":
            return GeminiFailureCategory.SERVER_ERROR_5XX, retry_delay, safe_msg

        return GeminiFailureCategory.UNKNOWN, None, safe_msg

    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return GeminiFailureCategory.SERVER_ERROR_5XX, None, safe_msg

    return GeminiFailureCategory.UNKNOWN, None, safe_msg


def _deterministic_fallback_summary(results: list[DelegationResult]) -> str:
    """Generate a structured deterministic summary from collected specialist agent results."""
    lines: list[str] = []
    successful = [r for r in results if r.status.value == "success"]
    failed = [r for r in results if r.status.value != "success"]

    if successful and not failed:
        for r in successful:
            lines.append(f"### {r.agent_name} Findings\n{r.content}\n")
    elif successful and failed:
        lines.append("### Partial Results\n")
        for r in successful:
            lines.append(f"**{r.agent_name} (Completed):**\n{r.content}\n")
        lines.append("### Incomplete Tasks\n")
        for r in failed:
            lines.append(
                f"**{r.agent_name} (Failed):** {r.error or 'Execution failed'}\n"
            )
    else:
        lines.append("### Execution Failed\n")
        for r in failed:
            lines.append(
                f"- **{r.agent_name}:** {r.error or 'Failed to complete execution.'}"
            )

    return "\n".join(lines).strip()


class GeminiService:
    """Service wrapping Google Gemini API with multi-model fallback for orchestrator."""

    def __init__(
        self,
        settings: GeminiSettings | None = None,
        client: genai.Client | None = None,
        tracker: ModelHealthTracker | None = None,
    ) -> None:
        self.settings = settings or get_gemini_settings()
        self._client = client
        self.tracker = tracker or ModelHealthTracker()

    @property
    def client(self) -> genai.Client:
        """Lazy-initialize and return the official google-genai Client."""
        if self._client is None:
            if (
                not self.settings.api_key
                or self.settings.api_key == "replace_with_your_api_key"
            ):
                raise GeminiConfigurationError(
                    "Google Gemini API key is missing or not configured. "
                    "Please set GOOGLE_API_KEY in your environment or .env file."
                )
            self._client = genai.Client(api_key=self.settings.api_key)
        return self._client

    async def _execute_with_model_fallback(
        self,
        operation_name: str,
        call_fn: Callable[[str], Awaitable[T]],
    ) -> tuple[T, str]:
        """Execute call_fn across configured candidate models with fallback and retries."""
        candidates = self.settings.model_candidates
        if not candidates:
            candidates = ["gemini-3.5-flash-lite"]

        # Filter candidates based on active failure cooldown
        available_models = [m for m in candidates if self.tracker.is_model_available(m)]
        for m in candidates:
            if m not in available_models:
                logger.info("Model %s is in cooldown; skipping.", m)

        if not available_models:
            logger.warning(
                "All Gemini candidate models are currently in cooldown or daily quota exhausted."
            )
            first_record = self.tracker.get_failure_record(candidates[0])
            if first_record:
                if first_record.failure_category == GeminiFailureCategory.NOT_FOUND_404:
                    raise GeminiConfigurationError(
                        f"Gemini model not found: {first_record.error_message}"
                    )
                if (
                    first_record.failure_category
                    == GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED
                ):
                    raise GeminiDailyQuotaExhaustedError(
                        f"Gemini daily quota exhausted: {first_record.error_message}"
                    )
                if first_record.failure_category == GeminiFailureCategory.RATE_LIMITED:
                    raise GeminiRateLimitError(
                        f"Gemini API rate limit exceeded: {first_record.error_message}"
                    )
                if first_record.failure_category == GeminiFailureCategory.TIMEOUT:
                    raise GeminiTimeoutError("Gemini request timed out.")
                if first_record.failure_category in (
                    GeminiFailureCategory.OVERLOADED_503,
                    GeminiFailureCategory.SERVER_ERROR_5XX,
                ):
                    raise GeminiServiceUnavailableError(
                        f"Gemini API service unavailable: {first_record.error_message}"
                    )
            raise GeminiDailyQuotaExhaustedError(
                "All Gemini candidate models are currently in cooldown or daily quota exhausted."
            )

        last_error: Exception | None = None
        last_category = GeminiFailureCategory.UNKNOWN
        last_safe_msg = "Unknown error"

        primary_model = candidates[0]

        for model_name in available_models:
            is_primary = model_name == primary_model

            if is_primary:
                logger.info("Gemini primary model: %s", model_name)
            else:
                logger.info("Switching to fallback: %s", model_name)

            max_attempts = 1 + max(0, self.settings.model_retry_attempts)

            for attempt in range(max_attempts):
                try:
                    result = await call_fn(model_name)
                    self.tracker.record_success(model_name)
                    if not is_primary:
                        logger.info("Fallback model succeeded: %s", model_name)
                    return result, model_name

                except Exception as exc:
                    category, retry_delay, safe_msg = classify_gemini_error(
                        exc, self.settings.api_key
                    )
                    last_error = exc
                    last_category = category
                    last_safe_msg = safe_msg

                    # Non-switchable errors: terminate candidate traversal immediately
                    if category == GeminiFailureCategory.AUTH_ERROR_401_403:
                        logger.error(
                            "Authentication/Permission error with Gemini API: %s",
                            safe_msg,
                        )
                        raise GeminiConfigurationError(
                            f"Gemini authentication failed: {safe_msg}"
                        ) from exc

                    if category == GeminiFailureCategory.INVALID_REQUEST_400:
                        logger.error(
                            "Invalid request to Gemini API (400): %s", safe_msg
                        )
                        raise GeminiAPIError(
                            f"Gemini API invalid request: {safe_msg}"
                        ) from exc

                    # Check for bounded retry on same model for transient issues
                    is_retriable = category in (
                        GeminiFailureCategory.OVERLOADED_503,
                        GeminiFailureCategory.TIMEOUT,
                        GeminiFailureCategory.SERVER_ERROR_5XX,
                    )

                    if is_retriable and attempt + 1 < max_attempts:
                        logger.warning(
                            "Transient error (%s) on model %s; retrying attempt %d/%d in %.1fs...",
                            category.value,
                            model_name,
                            attempt + 1,
                            max_attempts,
                            self.settings.model_retry_delay,
                        )
                        if self.settings.model_retry_delay > 0:
                            await asyncio.sleep(self.settings.model_retry_delay)
                        continue

                    # Record failure on tracker and log model transition
                    self.tracker.record_failure(
                        model_name=model_name,
                        category=category,
                        retry_after=retry_delay,
                        error_message=safe_msg,
                    )

                    if is_primary:
                        logger.warning(
                            "Primary model failed: %s",
                            category.value,
                        )
                    else:
                        logger.warning(
                            "Fallback model %s failed: %s",
                            model_name,
                            category.value,
                        )

                    break  # Break retry loop and move to next model

        # All available models failed
        logger.warning(
            "All Gemini candidate models failed for %s.",
            operation_name,
        )

        if last_category == GeminiFailureCategory.DAILY_QUOTA_EXHAUSTED:
            raise GeminiDailyQuotaExhaustedError(
                f"Gemini daily quota exhausted: {last_safe_msg}"
            ) from last_error
        elif last_category == GeminiFailureCategory.RATE_LIMITED:
            raise GeminiRateLimitError(
                f"Gemini API rate limit exceeded: {last_safe_msg}"
            ) from last_error
        elif last_category == GeminiFailureCategory.TIMEOUT:
            raise GeminiTimeoutError("Gemini request timed out.") from last_error
        elif last_category in (
            GeminiFailureCategory.OVERLOADED_503,
            GeminiFailureCategory.SERVER_ERROR_5XX,
        ):
            raise GeminiServiceUnavailableError(
                f"Gemini API service unavailable: {last_safe_msg}"
            ) from last_error
        elif last_category == GeminiFailureCategory.NOT_FOUND_404:
            raise GeminiConfigurationError(
                f"Gemini model not found: {last_safe_msg}"
            ) from last_error
        else:
            raise GeminiAPIError(f"Gemini API error: {last_safe_msg}") from last_error

    def fallback_plan(self, user_prompt: str) -> DelegationPlan:
        """Deterministic heuristic fallback when Gemini API is unavailable or disabled."""
        cleaned = user_prompt.lower()

        research_terms = {
            "file",
            "files",
            "read",
            "document",
            "documents",
            "report",
            "reports",
            "dataset",
            "datasets",
            "source_code",
            "note",
            "notes",
            "workspace",
            "summary",
            "summarize",
        }
        task_terms = {
            "task",
            "tasks",
            "todo",
            "deadline",
            "priority",
            "milestone",
            "assignee",
            "agent_info",
            "agents",
        }

        has_research = any(
            re.search(rf"\b{term}\b", cleaned) for term in research_terms
        )
        has_task = any(re.search(rf"\b{term}\b", cleaned) for term in task_terms)

        if has_research and has_task:
            is_seq = any(
                w in cleaned for w in ["then", "after", "based on", "subsequently"]
            )
            mode = ExecutionMode.SEQUENTIAL if is_seq else ExecutionMode.INDEPENDENT
            tasks = [
                DelegationTask(
                    step_id="step_1",
                    agent_target=AgentTarget.RESEARCH_AGENT,
                    prompt=user_prompt,
                ),
                DelegationTask(
                    step_id="step_2",
                    agent_target=AgentTarget.TASK_AGENT,
                    prompt=user_prompt,
                    depends_on=["step_1"] if is_seq else [],
                ),
            ]
            return DelegationPlan(
                reasoning="Request requires both research/notes and task management.",
                mode=mode,
                tasks=tasks,
            )

        if has_research:
            return DelegationPlan(
                reasoning="Request involves workspace file operations or research notes.",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.RESEARCH_AGENT,
                        prompt=user_prompt,
                    )
                ],
            )

        if has_task:
            return DelegationPlan(
                reasoning="Request involves task tracking or agent information.",
                mode=ExecutionMode.SINGLE,
                tasks=[
                    DelegationTask(
                        step_id="step_1",
                        agent_target=AgentTarget.TASK_AGENT,
                        prompt=user_prompt,
                    )
                ],
            )

        return DelegationPlan(
            reasoning="Request does not match research notes, workspace files, or task management capabilities.",
            mode=ExecutionMode.UNSUPPORTED,
            tasks=[],
            direct_response=(
                "I am ResearchMate, your academic research assistant. "
                "I can help you inspect workspace documents, manage research notes, "
                "and track research tasks and milestones. How can I assist you with your research?"
            ),
        )

    async def plan(
        self,
        user_prompt: str,
        context: dict[str, Any] | None = None,
        use_fallback_on_error: bool = False,
    ) -> DelegationPlan:
        """Formulate a delegation plan using Gemini API with multi-model fallback."""
        prompt_text = user_prompt.strip()
        if not prompt_text:
            return DelegationPlan(
                reasoning="Empty prompt",
                mode=ExecutionMode.UNSUPPORTED,
                tasks=[],
                direct_response="Please provide a non-empty research or task request.",
            )

        planning_input = prompt_text
        conversation_history = (context or {}).get("conversation_history")
        if conversation_history:
            planning_input = (
                f"--- Previous Conversation Context ---\n"
                f"{conversation_history}\n\n"
                f"--- Current User Request ---\n"
                f"{prompt_text}"
            )

        async def _do_plan(model_name: str) -> DelegationPlan:
            client = self.client
            config = types.GenerateContentConfig(
                system_instruction=ORCHESTRATOR_PLANNING_SYSTEM_PROMPT,
                temperature=self.settings.temperature,
                response_mime_type="application/json",
            )

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=planning_input,
                    config=config,
                ),
                timeout=self.settings.timeout_seconds,
            )

            raw_content = response.text or "{}"
            cleaned_json = _clean_json_markdown(raw_content)
            data = json.loads(cleaned_json)

            mode_str = data.get("mode", "unsupported").lower()
            try:
                mode = ExecutionMode(mode_str)
            except ValueError:
                mode = ExecutionMode.UNSUPPORTED

            tasks: list[DelegationTask] = []
            for t in data.get("tasks", []):
                target_str = t.get("agent_target", "none").lower()
                try:
                    target = AgentTarget(target_str)
                except ValueError:
                    target = AgentTarget.NONE

                tasks.append(
                    DelegationTask(
                        step_id=t.get("step_id", f"step_{len(tasks) + 1}"),
                        agent_target=target,
                        prompt=t.get("prompt", prompt_text),
                        depends_on=t.get("depends_on", []),
                        context=t.get("context", {}),
                    )
                )

            return DelegationPlan(
                reasoning=data.get("reasoning", "Gemini generated plan"),
                mode=mode,
                tasks=tasks,
                direct_response=data.get("direct_response"),
            )

        try:
            plan, _ = await self._execute_with_model_fallback("planning", _do_plan)
            return plan

        except GeminiConfigurationError:
            if use_fallback_on_error:
                logger.warning(
                    "Gemini unconfigured or auth failed; utilizing deterministic fallback planner."
                )
                return self.fallback_plan(prompt_text)
            raise

        except Exception as exc:
            safe_msg = _redact_secrets(str(exc), self.settings.api_key)
            logger.error("Gemini planning error: %s", safe_msg)
            if use_fallback_on_error:
                return self.fallback_plan(prompt_text)
            raise

    async def synthesize(
        self,
        user_prompt: str,
        plan: DelegationPlan,
        results: list[DelegationResult],
        use_fallback_on_error: bool = True,
    ) -> str:
        """Synthesize a final response from collected agent results using multi-model fallback."""
        if plan.mode == ExecutionMode.UNSUPPORTED and plan.direct_response:
            return plan.direct_response

        results_summary: list[dict[str, Any]] = []
        for r in results:
            results_summary.append(
                {
                    "step_id": r.step_id,
                    "agent": r.agent_name,
                    "status": r.status.value,
                    "output": r.content,
                    "error": r.error,
                }
            )

        synthesis_input = {
            "user_request": user_prompt,
            "plan_reasoning": plan.reasoning,
            "agent_results": results_summary,
        }

        async def _do_synthesize(model_name: str) -> str:
            client = self.client
            config = types.GenerateContentConfig(
                system_instruction=ORCHESTRATOR_SYNTHESIS_SYSTEM_PROMPT,
                temperature=self.settings.temperature,
            )

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=json.dumps(synthesis_input, indent=2),
                    config=config,
                ),
                timeout=self.settings.timeout_seconds,
            )
            return (response.text or "").strip()

        try:
            summary, _ = await self._execute_with_model_fallback(
                "synthesis", _do_synthesize
            )
            return summary

        except Exception as exc:
            safe_msg = _redact_secrets(str(exc), self.settings.api_key)
            logger.warning(
                "Gemini synthesis unavailable (%s); falling back to direct summary.",
                safe_msg,
            )
            if not use_fallback_on_error:
                raise GeminiAPIError(f"Gemini synthesis failed: {safe_msg}") from exc

            return _deterministic_fallback_summary(results)
