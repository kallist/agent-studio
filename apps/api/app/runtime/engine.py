from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable
from contextlib import suppress
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import JsonValue, ValidationError

from app.domain.contracts import (
    AgentContext,
    AgentDecision,
    AgentEvent,
    AgentPhase,
    AgentRun,
    AgentState,
    AgentStep,
    CancellationToken,
    EventSink,
    EventType,
    RuntimeInput,
    TerminationReason,
    ToolResult,
    ToolResultStatus,
)
from app.domain.errors import (
    InvalidAgentOutputError,
    ProviderExecutionError,
    ToolExecutionError,
    ToolNotFoundError,
)
from app.runtime.providers import DecisionProvider
from app.tools.registry import ToolExecutor

T = TypeVar("T")


class _CancellationRequested(Exception):
    pass


class AgentLoop:
    """Application-owned bounded loop over typed model decisions and controlled tools."""

    def __init__(self, provider: DecisionProvider, tools: ToolExecutor, runtime_name: str) -> None:
        self._provider = provider
        self._tools = tools
        self._runtime_name = runtime_name

    @property
    def is_configured(self) -> bool:
        return self._provider.is_configured

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun:
        started_at = datetime.now(UTC)
        steps: list[AgentStep] = []
        try:
            async with asyncio.timeout(runtime_input.limits.timeout_seconds):
                return await self._run_loop(
                    runtime_input,
                    emit,
                    cancellation,
                    started_at,
                    steps,
                )
        except _CancellationRequested:
            return self._terminal(
                runtime_input,
                steps,
                started_at,
                TerminationReason.CANCELLED,
                error="Agent run was cancelled by the user.",
            )
        except TimeoutError:
            return self._terminal(
                runtime_input,
                steps,
                started_at,
                TerminationReason.TIMEOUT,
                error=f"Agent run exceeded {runtime_input.limits.timeout_seconds:g} seconds.",
            )
        except InvalidAgentOutputError as exc:
            return self._terminal(
                runtime_input,
                steps,
                started_at,
                TerminationReason.INVALID_OUTPUT,
                error=self._bounded_error(str(exc)),
            )
        except ToolNotFoundError as exc:
            return self._terminal(
                runtime_input,
                steps,
                started_at,
                TerminationReason.TOOL_ERROR,
                error=self._bounded_error(str(exc)),
            )

    async def _run_loop(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None,
        started_at: datetime,
        steps: list[AgentStep],
    ) -> AgentRun:
        fingerprints: list[str] = []
        calls_per_tool: Counter[str] = Counter()

        for step_index in range(1, runtime_input.limits.max_steps + 1):
            step_started_at = datetime.now(UTC)
            self._check_cancelled(cancellation)
            await self._emit(
                emit,
                runtime_input,
                "step.started",
                {"step": step_index, "state": AgentPhase.WAITING_FOR_MODEL.value},
            )
            context = self._build_context(runtime_input, steps)
            decision, error = await self._get_decision(
                runtime_input,
                context,
                emit,
                cancellation,
                step_index,
            )
            if decision is None:
                return self._terminal(
                    runtime_input,
                    steps,
                    started_at,
                    error[0],
                    error=error[1],
                )

            if decision.action == "final":
                step = AgentStep(
                    index=step_index,
                    decision=decision,
                    started_at=step_started_at,
                    completed_at=datetime.now(UTC),
                )
                steps.append(step)
                await self._emit(
                    emit,
                    runtime_input,
                    "step.completed",
                    {"step": step_index, "action": "final"},
                )
                return self._terminal(
                    runtime_input,
                    steps,
                    started_at,
                    TerminationReason.COMPLETED,
                    final_output=decision.final_output,
                )

            call = decision.tool_call
            if call is None:
                return self._terminal(
                    runtime_input,
                    steps,
                    started_at,
                    TerminationReason.INVALID_OUTPUT,
                    error="Tool decision did not contain a tool call.",
                )
            await self._emit(
                emit,
                runtime_input,
                "tool.selected",
                {"step": step_index, "tool": call.name, "call_id": str(call.call_id)},
            )

            validation_error = self._validate_tool_call(
                runtime_input,
                call.name,
                call.arguments,
                fingerprints,
                calls_per_tool,
            )
            if validation_error is not None:
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    status=ToolResultStatus.FAILED,
                    error=validation_error,
                    latency_ms=0,
                )
                steps.append(
                    AgentStep(
                        index=step_index,
                        decision=decision,
                        tool_result=result,
                        started_at=step_started_at,
                        completed_at=datetime.now(UTC),
                    )
                )
                await self._emit(
                    emit,
                    runtime_input,
                    "tool.failed",
                    self._tool_payload(
                        step_index, result, call.arguments, include_duration=False
                    ),
                )
                await self._emit(
                    emit,
                    runtime_input,
                    "step.completed",
                    {"step": step_index, "action": "tool", "status": "failed"},
                )
                return self._terminal(
                    runtime_input,
                    steps,
                    started_at,
                    TerminationReason.INVALID_OUTPUT,
                    error=validation_error,
                )

            await self._emit(
                emit,
                runtime_input,
                "tool.started",
                {
                    "step": step_index,
                    "tool": call.name,
                    "call_id": str(call.call_id),
                    "arguments": call.arguments,
                    "state": AgentPhase.EXECUTING_TOOL.value,
                },
            )
            loop = asyncio.get_running_loop()
            tool_started = loop.time()
            try:
                result = await self._await_with_cancellation(
                    self._tools.execute(call, runtime_input.granted_permissions),
                    cancellation,
                )
            except ToolExecutionError as exc:
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.name,
                    status=ToolResultStatus.FAILED,
                    error=self._bounded_error(str(exc)),
                    latency_ms=round((loop.time() - tool_started) * 1000, 2),
                )
                steps.append(
                    AgentStep(
                        index=step_index,
                        decision=decision,
                        tool_result=result,
                        started_at=step_started_at,
                        completed_at=datetime.now(UTC),
                    )
                )
                await self._emit(
                    emit,
                    runtime_input,
                    "tool.failed",
                    self._tool_payload(step_index, result, call.arguments),
                )
                await self._emit(
                    emit,
                    runtime_input,
                    "step.completed",
                    {"step": step_index, "action": "tool", "status": "failed"},
                )
                return self._terminal(
                    runtime_input,
                    steps,
                    started_at,
                    TerminationReason.TOOL_ERROR,
                    error=self._bounded_error(str(exc)),
                )

            fingerprint = self._fingerprint(call.name, call.arguments)
            fingerprints.append(fingerprint)
            calls_per_tool[call.name] += 1
            steps.append(
                AgentStep(
                    index=step_index,
                    decision=decision,
                    tool_result=result,
                    started_at=step_started_at,
                    completed_at=datetime.now(UTC),
                )
            )
            await self._emit(
                emit,
                runtime_input,
                "tool.completed",
                self._tool_payload(step_index, result, call.arguments),
            )
            await self._emit(
                emit,
                runtime_input,
                "step.completed",
                {"step": step_index, "action": "tool", "status": "completed"},
            )

        return self._terminal(
            runtime_input,
            steps,
            started_at,
            TerminationReason.MAX_STEPS,
            error=f"Agent reached the maximum of {runtime_input.limits.max_steps} steps.",
        )

    async def _get_decision(
        self,
        runtime_input: RuntimeInput,
        context: AgentContext,
        emit: EventSink,
        cancellation: CancellationToken | None,
        step_index: int,
    ) -> tuple[AgentDecision | None, tuple[TerminationReason, str]]:
        attempts = runtime_input.limits.invalid_output_retries + 1
        for attempt in range(1, attempts + 1):
            loop = asyncio.get_running_loop()
            decision_started = loop.time()
            await self._emit(
                emit,
                runtime_input,
                "llm.started",
                {
                    "step": step_index,
                    "attempt": attempt,
                    "runtime": self._runtime_name,
                    "context_chars": len(context.model_dump_json()),
                },
            )
            try:
                raw_decision = await self._await_with_cancellation(
                    self._provider.decide(context), cancellation
                )
                decision = AgentDecision.model_validate(raw_decision)
                if len(decision.model_dump_json()) > runtime_input.limits.max_decision_chars:
                    raise InvalidAgentOutputError(
                        "Provider decision exceeded its configured size limit."
                    )
            except (InvalidAgentOutputError, ValidationError) as exc:
                if attempt < attempts:
                    await self._emit(
                        emit,
                        runtime_input,
                        "llm.retrying",
                        {
                            "step": step_index,
                            "attempt": attempt,
                            "reason": "invalid_output",
                            "duration_ms": round((loop.time() - decision_started) * 1000, 2),
                        },
                    )
                    continue
                return None, (
                    TerminationReason.INVALID_OUTPUT,
                    self._bounded_error(
                        f"Provider returned invalid structured output ({type(exc).__name__})."
                    ),
                )
            except ProviderExecutionError as exc:
                return None, (
                    TerminationReason.PROVIDER_ERROR,
                    self._bounded_error(str(exc)),
                )
            except _CancellationRequested:
                raise
            except Exception:
                return None, (
                    TerminationReason.PROVIDER_ERROR,
                    "Provider failed unexpectedly.",
                )
            await self._emit(
                emit,
                runtime_input,
                "llm.completed",
                {
                    "step": step_index,
                    "attempt": attempt,
                    "action": decision.action,
                    "duration_ms": round((loop.time() - decision_started) * 1000, 2),
                },
            )
            return decision, (TerminationReason.COMPLETED, "")
        raise AssertionError("unreachable")

    def _build_context(self, runtime_input: RuntimeInput, steps: list[AgentStep]) -> AgentContext:
        specs = self._tools.registry.specs(runtime_input.agent.tools)
        included: list[AgentStep] = []
        for step in reversed(steps):
            candidate = AgentContext(
                instructions=runtime_input.agent.instructions,
                user_input=runtime_input.user_input,
                tools=specs,
                steps=[step, *included],
                memory=runtime_input.memory,
                omitted_steps=len(steps) - len(included) - 1,
            )
            if len(candidate.model_dump_json()) > runtime_input.limits.max_context_chars:
                break
            included.insert(0, step)
        context = AgentContext(
            instructions=runtime_input.agent.instructions,
            user_input=runtime_input.user_input,
            tools=specs,
            steps=included,
            memory=runtime_input.memory,
            omitted_steps=len(steps) - len(included),
        )
        if len(context.model_dump_json()) > runtime_input.limits.max_context_chars:
            raise InvalidAgentOutputError("Base agent context exceeds its configured limit.")
        return context

    def _validate_tool_call(
        self,
        runtime_input: RuntimeInput,
        name: str,
        arguments: dict[str, JsonValue],
        fingerprints: list[str],
        calls_per_tool: Counter[str],
    ) -> str | None:
        if name not in runtime_input.agent.tools:
            return f"Provider selected disabled tool '{name}'."
        try:
            self._tools.registry.get(name)
        except ToolNotFoundError as exc:
            return str(exc)
        fingerprint = self._fingerprint(name, arguments)
        if fingerprints and fingerprints[-1] == fingerprint:
            return f"Blocked consecutive duplicate call to tool '{name}'."
        if calls_per_tool[name] >= runtime_input.limits.max_calls_per_tool:
            return f"Tool '{name}' exceeded its per-run call limit."
        return None

    @staticmethod
    def _fingerprint(name: str, arguments: dict[str, JsonValue]) -> str:
        return f"{name}:{json.dumps(arguments, sort_keys=True, separators=(',', ':'))}"

    @staticmethod
    def _check_cancelled(cancellation: CancellationToken | None) -> None:
        if cancellation is not None and cancellation.is_cancelled:
            raise _CancellationRequested

    async def _await_with_cancellation(
        self, awaitable: Awaitable[T], cancellation: CancellationToken | None
    ) -> T:
        if cancellation is None:
            return await awaitable
        operation = asyncio.ensure_future(awaitable)
        cancelled = asyncio.create_task(cancellation.wait())
        try:
            if cancellation.is_cancelled:
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
                raise _CancellationRequested
            done, _ = await asyncio.wait(
                {operation, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done:
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
                raise _CancellationRequested
            return await operation
        finally:
            if not operation.done():
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
            cancelled.cancel()
            with suppress(asyncio.CancelledError):
                await cancelled

    async def _emit(
        self,
        emit: EventSink,
        runtime_input: RuntimeInput,
        event_type: EventType,
        payload: dict[str, object],
    ) -> None:
        step = payload.get("step_index", payload.get("step"))
        call_id = payload.get("tool_call_id", payload.get("call_id"))
        duration = payload.get("duration_ms", payload.get("latency_ms"))
        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type=event_type,
                step_index=step if isinstance(step, int) else None,
                tool_call_id=UUID(call_id) if isinstance(call_id, str) else None,
                duration_ms=(
                    float(duration)
                    if isinstance(duration, (int, float)) and duration >= 0
                    else None
                ),
                payload=payload,
            )
        )

    @staticmethod
    def _tool_payload(
        step_index: int,
        result: ToolResult,
        arguments: dict[str, JsonValue],
        *,
        include_duration: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "step": step_index,
            "tool": result.tool_name,
            "call_id": str(result.call_id),
            "arguments": arguments,
        }
        if include_duration:
            payload["latency_ms"] = result.latency_ms
        if result.output is not None:
            if result.tool_name == "knowledge_search":
                raw_results = result.output.get("results")
                citations: list[dict[str, JsonValue]] = []
                if isinstance(raw_results, list):
                    for raw in raw_results:
                        if isinstance(raw, dict):
                            citations.append(
                                {
                                    key: value
                                    for key, value in raw.items()
                                    if key != "content"
                                }
                            )
                query = result.output.get("query")
                algorithm = result.output.get("algorithm")
                payload.update(
                    {
                        "query": query,
                        "top_k": arguments.get("top_k"),
                        "retrieval_mode": algorithm,
                        "result_count": len(citations),
                        "citations": citations,
                        "result": {
                            "query": query,
                            "algorithm": algorithm,
                            "result_count": len(citations),
                            "results": citations,
                        },
                    }
                )
            else:
                payload["result"] = result.output
        if result.error is not None:
            payload["error"] = result.error
        return payload

    @staticmethod
    def _terminal(
        runtime_input: RuntimeInput,
        steps: list[AgentStep],
        started_at: datetime,
        reason: TerminationReason,
        *,
        final_output: str | None = None,
        error: str | None = None,
    ) -> AgentRun:
        return AgentRun(
            run_id=runtime_input.run_id,
            state=AgentState(
                phase=AgentPhase.TERMINATED,
                current_step=len(steps),
                started_at=started_at,
            ),
            steps=list(steps),
            termination_reason=reason,
            final_output=final_output,
            error=error,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    @staticmethod
    def _bounded_error(message: str, limit: int = 2_000) -> str:
        if len(message) <= limit:
            return message
        return f"{message[: limit - 14]}...[truncated]"
