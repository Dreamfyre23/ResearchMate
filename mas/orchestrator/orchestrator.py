"""Central Gemini-powered orchestrator for ResearchMate (Phase 10).

Coordinates specialized agents (Research Agent and Task Agent) using the Google Gemini API,
enforcing structured delegation contracts, bounded execution, and robust failure handling.
"""

import asyncio
import logging
import time

from client_mcp.host import MCPHost
from mas.agents.models import AgentRequest, AgentResponse
from mas.agents.research_agent.agent import ResearchAgent
from mas.agents.task_agent.agent import TaskAgent
from mas.config.settings import OrchestratorSettings, get_orchestrator_settings
from mas.orchestrator.exceptions import (
    DelegationLimitExceededError,
)
from mas.orchestrator.gemini_service import GeminiService
from mas.orchestrator.models import (
    AgentTarget,
    DelegationPlan,
    DelegationResult,
    DelegationTask,
    ExecutionMode,
    ExecutionStatus,
    OrchestratorRequest,
    OrchestratorResponse,
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """Central orchestrator coordinating multi-agent workflows via Gemini."""

    def __init__(
        self,
        gemini_service: GeminiService | None = None,
        research_agent: ResearchAgent | None = None,
        task_agent: TaskAgent | None = None,
        mcp_host: MCPHost | None = None,
        settings: OrchestratorSettings | None = None,
    ) -> None:
        self.settings = settings or get_orchestrator_settings()
        self.gemini_service = gemini_service or GeminiService()
        self.mcp_host = mcp_host

        # Lazy/provided agent instances
        self._research_agent = research_agent
        self._task_agent = task_agent

    @property
    def research_agent(self) -> ResearchAgent:
        """Return or instantiate ResearchAgent using available MCPHost."""
        if self._research_agent is None:
            if self.mcp_host is None:
                raise ValueError(
                    "Cannot initialize ResearchAgent without an MCPHost instance."
                )
            self._research_agent = ResearchAgent(mcp_host=self.mcp_host)
        return self._research_agent

    @property
    def task_agent(self) -> TaskAgent:
        """Return or instantiate TaskAgent using available MCPHost."""
        if self._task_agent is None:
            if self.mcp_host is None:
                raise ValueError(
                    "Cannot initialize TaskAgent without an MCPHost instance."
                )
            self._task_agent = TaskAgent(mcp_host=self.mcp_host)
        return self._task_agent

    async def _execute_single_task(
        self,
        task: DelegationTask,
        shared_context: dict[str, str],
        request_context: dict[str, str] | None = None,
    ) -> DelegationResult:
        """Execute a single agent delegation step with timeout and error handling."""
        start_time = time.monotonic()

        # Resolve agent
        if task.agent_target == AgentTarget.RESEARCH_AGENT:
            agent = self.research_agent
            agent_display_name = "Research Agent"
        elif task.agent_target == AgentTarget.TASK_AGENT:
            agent = self.task_agent
            agent_display_name = "Task Agent"
        else:
            return DelegationResult(
                step_id=task.step_id,
                agent_name="None",
                prompt=task.prompt,
                status=ExecutionStatus.SKIPPED,
                content="",
                error="No valid agent targeted for this step.",
            )

        # Build prompt, incorporating relevant upstream dependency content if present
        effective_prompt = task.prompt
        if task.depends_on:
            upstream_snippets: list[str] = []
            for dep_id in task.depends_on:
                if shared_context.get(dep_id):
                    upstream_snippets.append(
                        f"Result from {dep_id}:\n{shared_context[dep_id]}"
                    )
            if upstream_snippets:
                effective_prompt = (
                    f"{task.prompt}\n\n"
                    f"--- Upstream Findings ---\n" + "\n\n".join(upstream_snippets)
                )

        merged_context = dict(task.context)
        if request_context:
            for k, v in request_context.items():
                if k not in merged_context:
                    merged_context[k] = v

        agent_req = AgentRequest(
            prompt=effective_prompt,
            context=merged_context,
        )

        try:
            logger.info("Delegating %s to %s", task.step_id, agent_display_name)
            agent_res: AgentResponse = await asyncio.wait_for(
                agent.run(agent_req),
                timeout=self.settings.agent_timeout_seconds,
            )
            elapsed = time.monotonic() - start_time

            if agent_res.is_success:
                status = ExecutionStatus.SUCCESS
                content = agent_res.content
                err = None
            else:
                status = ExecutionStatus.FAILED
                content = agent_res.content
                err = agent_res.error or "Agent reported execution failure."

            return DelegationResult(
                step_id=task.step_id,
                agent_name=agent_display_name,
                prompt=effective_prompt,
                status=status,
                content=content,
                tool_calls=agent_res.tool_calls,
                error=err,
                execution_time_seconds=elapsed,
            )

        except TimeoutError:
            elapsed = time.monotonic() - start_time
            logger.error(
                "Delegation step %s timed out on %s after %.1fs",
                task.step_id,
                agent_display_name,
                self.settings.agent_timeout_seconds,
            )
            return DelegationResult(
                step_id=task.step_id,
                agent_name=agent_display_name,
                prompt=effective_prompt,
                status=ExecutionStatus.TIMED_OUT,
                content="",
                error=f"Agent execution timed out after {self.settings.agent_timeout_seconds}s.",
                execution_time_seconds=elapsed,
            )

        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start_time
            logger.error(
                "Delegation step %s failed with exception: %s", task.step_id, exc
            )
            return DelegationResult(
                step_id=task.step_id,
                agent_name=agent_display_name,
                prompt=effective_prompt,
                status=ExecutionStatus.FAILED,
                content="",
                error=str(exc),
                execution_time_seconds=elapsed,
            )

    async def run(self, request: OrchestratorRequest | str) -> OrchestratorResponse:
        """Run the end-to-end orchestration flow for a user request."""
        if isinstance(request, str):
            request = OrchestratorRequest(prompt=request)

        user_prompt = request.prompt.strip()
        if not user_prompt:
            return OrchestratorResponse(
                content="Please provide a non-empty instruction or question.",
                is_success=False,
                errors=["Empty prompt received."],
            )

        # 1. Gemini Planning Phase
        logger.info("Formulating delegation plan via GeminiService...")
        plan: DelegationPlan = await self.gemini_service.plan(
            user_prompt,
            context=request.context,
            use_fallback_on_error=True,
        )

        # 2. Check bounds on delegation steps
        if len(plan.tasks) > self.settings.max_delegation_steps:
            raise DelegationLimitExceededError(
                f"Delegation plan contains {len(plan.tasks)} steps, "
                f"exceeding maximum limit of {self.settings.max_delegation_steps}."
            )

        # 3. Handle Unsupported / Direct response mode
        if plan.mode == ExecutionMode.UNSUPPORTED:
            direct_reply = plan.direct_response or (
                "I am ResearchMate. I can help you search workspace files, "
                "manage research notes, and track tasks. How can I help with your research?"
            )
            return OrchestratorResponse(
                content=direct_reply,
                plan=plan,
                results=[],
                is_success=True,
            )

        # 4. Execute delegation tasks according to mode
        results: list[DelegationResult] = []
        shared_context: dict[str, str] = {}

        if plan.mode in (ExecutionMode.SINGLE, ExecutionMode.INDEPENDENT):
            # Tasks can run concurrently
            if len(plan.tasks) == 1:
                res = await self._execute_single_task(
                    plan.tasks[0], shared_context, request.context
                )
                results.append(res)
            else:
                concurrent_coros = [
                    self._execute_single_task(t, shared_context, request.context)
                    for t in plan.tasks
                ]
                gathered = await asyncio.gather(*concurrent_coros)
                results.extend(gathered)

        elif plan.mode == ExecutionMode.SEQUENTIAL:
            # Tasks execute sequentially, propagating upstream results
            for task in plan.tasks:
                # If dependencies exist, check if all upstream dependencies succeeded
                dependency_failed = False
                for dep in task.depends_on:
                    dep_res = next((r for r in results if r.step_id == dep), None)
                    if dep_res and dep_res.status != ExecutionStatus.SUCCESS:
                        dependency_failed = True
                        break

                if dependency_failed:
                    logger.warning(
                        "Skipping %s because upstream dependency failed.", task.step_id
                    )
                    results.append(
                        DelegationResult(
                            step_id=task.step_id,
                            agent_name=task.agent_target.value,
                            prompt=task.prompt,
                            status=ExecutionStatus.SKIPPED,
                            content="",
                            error=f"Upstream dependency failed; step {task.step_id} skipped.",
                        )
                    )
                    continue

                res = await self._execute_single_task(
                    task, shared_context, request.context
                )
                results.append(res)
                if res.status == ExecutionStatus.SUCCESS:
                    shared_context[task.step_id] = res.content

        # 5. Synthesize final response
        logger.info("Synthesizing final response...")
        final_content = await self.gemini_service.synthesize(
            user_prompt=user_prompt,
            plan=plan,
            results=results,
            use_fallback_on_error=True,
        )

        all_errors = [r.error for r in results if r.error]
        is_success = len(all_errors) == 0 and any(
            r.status == ExecutionStatus.SUCCESS for r in results
        )

        return OrchestratorResponse(
            content=final_content,
            plan=plan,
            results=results,
            is_success=is_success,
            errors=all_errors,
            metadata={
                "mode": plan.mode.value,
                "step_count": len(results),
            },
        )
