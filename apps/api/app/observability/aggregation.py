from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.domain.contracts import (
    AgentEvent,
    DashboardObservability,
    RunObservability,
    RunResult,
    RunStatus,
    ToolCallCounts,
    ToolCallObservation,
    UsageMetrics,
)

_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


@dataclass
class _ToolState:
    tool_call_id: UUID
    tool_name: str = "unknown"
    step_index: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    status: Literal["running", "completed", "failed", "unknown"] = "unknown"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error_summary: str | None = None


def _uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _step_index(event: AgentEvent) -> int | None:
    if event.step_index is not None:
        return event.step_index
    value = event.payload.get("step_index", event.payload.get("step"))
    return value if isinstance(value, int) and value >= 1 else None


def _duration(started_at: datetime | None, completed_at: datetime | None) -> float | None:
    if started_at is None or completed_at is None:
        return None
    return round(max(0.0, (completed_at - started_at).total_seconds() * 1000), 2)


def _usage(events: list[AgentEvent]) -> UsageMetrics:
    values: dict[str, list[int]] = {
        "input_tokens": [],
        "output_tokens": [],
        "total_tokens": [],
    }
    for event in events:
        if event.usage is None:
            continue
        for name in values:
            value = getattr(event.usage, name)
            if value is not None:
                values[name].append(value)
    return UsageMetrics(
        input_tokens=sum(values["input_tokens"]) if values["input_tokens"] else None,
        output_tokens=sum(values["output_tokens"]) if values["output_tokens"] else None,
        total_tokens=sum(values["total_tokens"]) if values["total_tokens"] else None,
    )


def _tool_observations(events: list[AgentEvent]) -> list[ToolCallObservation]:
    states: dict[UUID, _ToolState] = {}
    order: list[UUID] = []
    for event in events:
        call_id = event.tool_call_id or _uuid(
            event.payload.get("tool_call_id", event.payload.get("call_id"))
        )
        if call_id is None:
            continue
        if call_id not in states:
            states[call_id] = _ToolState(tool_call_id=call_id)
            order.append(call_id)
        state = states[call_id]
        tool = event.payload.get("tool")
        if isinstance(tool, str):
            state.tool_name = tool
        state.step_index = state.step_index or _step_index(event)
        arguments = event.payload.get("arguments")
        if isinstance(arguments, dict):
            state.input = arguments
        if event.type == "tool.started":
            state.started_at = event.timestamp
            state.status = "running"
        elif event.type in {"tool.completed", "tool.failed"}:
            state.completed_at = event.timestamp
            state.status = "completed" if event.type == "tool.completed" else "failed"
            state.duration_ms = event.duration_ms
            result = event.payload.get("result")
            if isinstance(result, dict):
                state.output = result
            error = event.payload.get("error")
            if isinstance(error, str):
                state.error_summary = error
    observations: list[ToolCallObservation] = []
    for call_id in order:
        state = states[call_id]
        observations.append(
            ToolCallObservation(
                tool_call_id=state.tool_call_id,
                tool_name=state.tool_name,
                step_index=state.step_index,
                started_at=state.started_at,
                completed_at=state.completed_at,
                duration_ms=state.duration_ms
                if state.duration_ms is not None
                else _duration(state.started_at, state.completed_at),
                status=state.status,
                input=state.input,
                output=state.output,
                error_summary=state.error_summary,
            )
        )
    return observations


def aggregate_run(run: RunResult, events: list[AgentEvent]) -> RunObservability:
    """Derive one consistent run view from the persisted Run and RunEvent facts."""

    ordered = sorted(events, key=lambda event: event.sequence)
    started = next((event for event in ordered if event.type == "run.started"), None)
    terminal = next((event for event in reversed(ordered) if event.type in _TERMINAL_EVENTS), None)
    tools = _tool_observations(ordered)
    steps = [_step_index(event) for event in ordered]
    observed_steps = [step for step in steps if step is not None]
    terminal_steps = terminal.payload.get("steps") if terminal is not None else None
    step_count = (
        terminal_steps
        if isinstance(terminal_steps, int) and terminal_steps >= 0
        else max(observed_steps, default=0)
    )
    runtime = started.payload.get("runtime") if started is not None else None
    provider = started.payload.get("provider") if started is not None else None
    termination_reason = (
        terminal.payload.get("termination_reason") if terminal is not None else None
    )
    error_category = terminal.payload.get("error_category") if terminal is not None else None
    error_summary = terminal.payload.get("error") if terminal is not None else run.error
    duration_ms = terminal.duration_ms if terminal is not None else None
    if duration_ms is None:
        duration_ms = _duration(
            started.timestamp if started else None,
            terminal.timestamp if terminal else None,
        )
    succeeded = sum(tool.status == "completed" for tool in tools)
    failed = sum(tool.status == "failed" for tool in tools)
    return RunObservability(
        run_id=run.id,
        agent_id=run.agent_id,
        runtime_type=runtime if isinstance(runtime, str) else None,
        provider_type=provider if isinstance(provider, str) else None,
        status=run.status,
        termination_reason=termination_reason if isinstance(termination_reason, str) else None,
        created_at=run.created_at,
        started_at=started.timestamp if started else None,
        terminal_at=terminal.timestamp if terminal else None,
        duration_ms=duration_ms,
        event_count=len(ordered),
        step_count=step_count,
        tool_calls=ToolCallCounts(total=len(tools), succeeded=succeeded, failed=failed),
        usage=_usage(ordered),
        error_category=error_category if isinstance(error_category, str) else None,
        error_summary=error_summary if isinstance(error_summary, str) else None,
        event_statistics=dict(Counter(event.type for event in ordered)),
        tools=tools,
    )


def aggregate_dashboard(
    runs: list[RunResult],
    events_by_run: dict[UUID, list[AgentEvent]],
    *,
    status_counts: Mapping[RunStatus, int] | None = None,
) -> DashboardObservability:
    summaries = [aggregate_run(run, events_by_run.get(run.id, [])) for run in runs]
    counts = status_counts or Counter(item.status for item in summaries)
    completed = counts.get(RunStatus.COMPLETED, 0)
    failed = counts.get(RunStatus.FAILED, 0)
    cancelled = counts.get(RunStatus.CANCELLED, 0)
    running = counts.get(RunStatus.RUNNING, 0)
    terminal_for_rate = completed + failed
    durations = [item.duration_ms for item in summaries if item.duration_ms is not None]
    return DashboardObservability(
        total_runs=sum(counts.values()),
        completed=completed,
        failed=failed,
        cancelled=cancelled,
        running=running,
        success_rate=completed / terminal_for_rate if terminal_for_rate else None,
        average_duration_ms=round(sum(durations) / len(durations), 2) if durations else None,
        recent_runs=summaries[:30],
    )
