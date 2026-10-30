"""Google Gemini API service integration for central orchestrator (Phase 10).

Interacts with the Google Gemini API using the official google-genai SDK for request
understanding, agent delegation planning, and response synthesis.
"""

import asyncio
import json
import logging
import re
from typing import Any

from google import genai
from google.genai import errors, types

from mas.config.settings import GeminiSettings, get_gemini_settings
from mas.orchestrator.exceptions import (
    GeminiAPIError,
    GeminiConfigurationError,
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


class GeminiService:
    """Service wrapping Google Gemini API for orchestrator planning and synthesis."""

    def __init__(
        self,
        settings: GeminiSettings | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self.settings = settings or get_gemini_settings()
        self._client = client

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
            # Check for sequence words
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

        # Neither research nor task
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
        """Formulate a delegation plan using Gemini API."""
        prompt_text = user_prompt.strip()
        if not prompt_text:
            return DelegationPlan(
                reasoning="Empty prompt",
                mode=ExecutionMode.UNSUPPORTED,
                tasks=[],
                direct_response="Please provide a non-empty research or task request.",
            )

        # Incorporate prior conversation context if present
        planning_input = prompt_text
        conversation_history = (context or {}).get("conversation_history")
        if conversation_history:
            planning_input = (
                f"--- Previous Conversation Context ---\n"
                f"{conversation_history}\n\n"
                f"--- Current User Request ---\n"
                f"{prompt_text}"
            )

        try:
            # Verify client configuration
            client = self.client

            config = types.GenerateContentConfig(
                system_instruction=ORCHESTRATOR_PLANNING_SYSTEM_PROMPT,
                temperature=self.settings.temperature,
                response_mime_type="application/json",
            )

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.settings.model,
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

        except GeminiConfigurationError:
            if use_fallback_on_error:
                logger.warning(
                    "Gemini unconfigured; utilizing deterministic fallback planner."
                )
                return self.fallback_plan(prompt_text)
            raise

        except TimeoutError as exc:
            logger.error("Gemini request timed out: %s", exc)
            if use_fallback_on_error:
                return self.fallback_plan(prompt_text)
            raise GeminiTimeoutError("Gemini request timed out.") from exc

        except errors.APIError as exc:
            safe_msg = _redact_secrets(str(exc), self.settings.api_key)
            logger.error("Gemini API error during planning: %s", safe_msg)
            if getattr(exc, "code", None) == 429:
                if use_fallback_on_error:
                    return self.fallback_plan(prompt_text)
                raise GeminiRateLimitError(
                    f"Gemini API rate limit exceeded: {safe_msg}"
                ) from exc
            if getattr(exc, "code", None) == 404:
                if use_fallback_on_error:
                    return self.fallback_plan(prompt_text)
                raise GeminiConfigurationError(
                    f"Gemini model not found: {safe_msg}"
                ) from exc
            if getattr(exc, "code", None) == 503:
                if use_fallback_on_error:
                    return self.fallback_plan(prompt_text)
                raise GeminiServiceUnavailableError(
                    f"Gemini API service unavailable: {safe_msg}"
                ) from exc
            if use_fallback_on_error:
                return self.fallback_plan(prompt_text)
            raise GeminiAPIError(f"Gemini API error: {safe_msg}") from exc

        except Exception as exc:
            safe_msg = _redact_secrets(str(exc), self.settings.api_key)
            logger.error("Unexpected error communicating with Gemini API: %s", safe_msg)
            if use_fallback_on_error:
                return self.fallback_plan(prompt_text)
            raise GeminiServiceUnavailableError(
                f"Gemini API service unavailable: {safe_msg}"
            ) from exc

    async def synthesize(
        self,
        user_prompt: str,
        plan: DelegationPlan,
        results: list[DelegationResult],
        use_fallback_on_error: bool = True,
    ) -> str:
        """Synthesize a coherent final response from collected agent results."""
        # If unsupported mode, return direct response
        if plan.mode == ExecutionMode.UNSUPPORTED and plan.direct_response:
            return plan.direct_response

        # Format results payload for synthesis
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

        try:
            client = self.client
            config = types.GenerateContentConfig(
                system_instruction=ORCHESTRATOR_SYNTHESIS_SYSTEM_PROMPT,
                temperature=self.settings.temperature,
            )

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.settings.model,
                    contents=json.dumps(synthesis_input, indent=2),
                    config=config,
                ),
                timeout=self.settings.timeout_seconds,
            )
            return (response.text or "").strip()

        except Exception as exc:
            safe_msg = _redact_secrets(str(exc), self.settings.api_key)
            logger.warning(
                "Gemini synthesis unavailable (%s); falling back to direct summary.",
                safe_msg,
            )
            if not use_fallback_on_error:
                raise GeminiAPIError(f"Gemini synthesis failed: {safe_msg}") from exc

            # Deterministic fallback summary
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
