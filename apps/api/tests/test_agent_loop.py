from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.contracts import (
    AgentDecision,
    AgentDefinition,
    AgentEvent,
    CancellationToken,
    RuntimeInput,
    RuntimeLimits,
    RuntimeMode,
    TerminationReason,
    ToolCall,
)
from app.domain.errors import ProviderExecutionError
from app.runtime.engine import AgentLoop
from app.tools.registry import ToolExecutor, default_tool_registry


class ScriptedProvider:
    def __init__(self, decisions: list[object]) -> None:
        self.decisions = decisions
        self.calls = 0

    @property
    def is_configured(self) -> bool:
        return True

    async def decide(self, context: object) -> object:
        del context
        decision = self.decisions[self.calls]
        self.calls += 1
        if isinstance(decision, Exception):
            raise decision
        return decision


def definition(tools: list[str] | None = None) -> AgentDefinition:
    return AgentDefinition(
        id=uuid4(),
        name="Test Agent",
        instructions="Complete the task using only enabled tools.",
        runtime_mode=RuntimeMode.MOCK,
        tools=["calculator"] if tools is None else tools,
        created_at=datetime.now(UTC),
    )


async def execute(
    provider: object,
    *,
    limits: RuntimeLimits | None = None,
    cancellation: CancellationToken | None = None,
    agent_definition: AgentDefinition | None = None,
) -> tuple[object, list[AgentEvent]]:
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    runtime = AgentLoop(
        provider,  # type: ignore[arg-type]
        ToolExecutor(default_tool_registry()),
        runtime_name="test",
    )
    result = await runtime.run(
        RuntimeInput(
            run_id=uuid4(),
            agent=agent_definition or definition(),
            user_input="test",
            limits=limits or RuntimeLimits(),
        ),
        collect,
        cancellation,
    )
    return result, events


@pytest.mark.asyncio
async def test_normal_answer_completes_without_tool() -> None:
    provider = ScriptedProvider([AgentDecision(action="final", final_output="done")])

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.COMPLETED
    assert result.final_output == "done"
    assert len(result.steps) == 1
    assert all(event.type != "tool.started" for event in events)


@pytest.mark.asyncio
async def test_single_tool_call_adds_observation_then_completes() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "1 + 2"}),
            ),
            AgentDecision(action="final", final_output="3"),
        ]
    )

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.COMPLETED
    assert result.steps[0].tool_result is not None
    assert result.steps[0].tool_result.output == {"result": "3"}
    assert [event.type for event in events].count("tool.completed") == 1


@pytest.mark.asyncio
async def test_multiple_tool_calls_are_ordered_and_bounded() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "1 + 2"}),
            ),
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "3 * 4"}),
            ),
            AgentDecision(action="final", final_output="12"),
        ]
    )

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.COMPLETED
    assert [step.tool_result.output for step in result.steps[:2] if step.tool_result] == [
        {"result": "3"},
        {"result": "12"},
    ]
    assert [event.type for event in events].count("tool.completed") == 2


@pytest.mark.asyncio
async def test_tool_failure_terminates_with_tool_error() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "1 / 0"}),
            )
        ]
    )

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.TOOL_ERROR
    assert "Division by zero" in result.error
    assert events[-2].type == "tool.failed"
    assert result.steps[0].tool_result is not None
    assert result.steps[0].tool_result.error is not None


@pytest.mark.asyncio
async def test_malformed_output_terminates_without_regex_parsing() -> None:
    provider = ScriptedProvider([{"action": "tool", "tool_call": "not-an-object"}])

    result, _ = await execute(provider, limits=RuntimeLimits(invalid_output_retries=0))

    assert result.termination_reason == TerminationReason.INVALID_OUTPUT
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_invalid_output_retry_is_limited_and_can_recover() -> None:
    provider = ScriptedProvider(
        [
            {"action": "unknown"},
            AgentDecision(action="final", final_output="recovered"),
        ]
    )

    result, events = await execute(provider, limits=RuntimeLimits(invalid_output_retries=1))

    assert result.termination_reason == TerminationReason.COMPLETED
    assert result.final_output == "recovered"
    assert provider.calls == 2
    assert [event.type for event in events].count("llm.retrying") == 1


@pytest.mark.asyncio
async def test_max_steps_terminates_after_exact_limit() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "1 + 1"}),
            ),
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": "2 + 2"}),
            ),
        ]
    )

    result, _ = await execute(provider, limits=RuntimeLimits(max_steps=2))

    assert result.termination_reason == TerminationReason.MAX_STEPS
    assert len(result.steps) == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_cancellation_interrupts_an_in_flight_provider_call() -> None:
    started = asyncio.Event()

    class BlockingProvider:
        @property
        def is_configured(self) -> bool:
            return True

        async def decide(self, context: object) -> object:
            del context
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    cancellation = CancellationToken()
    task = asyncio.create_task(execute(BlockingProvider(), cancellation=cancellation))
    await asyncio.wait_for(started.wait(), timeout=1)
    cancellation.cancel()
    result, _ = await asyncio.wait_for(task, timeout=1)

    assert result.termination_reason == TerminationReason.CANCELLED


@pytest.mark.asyncio
async def test_total_timeout_interrupts_provider() -> None:
    cancelled = asyncio.Event()

    class SlowProvider:
        @property
        def is_configured(self) -> bool:
            return True

        async def decide(self, context: object) -> object:
            del context
            try:
                await asyncio.sleep(1)
                return AgentDecision(action="final", final_output="late")
            except asyncio.CancelledError:
                cancelled.set()
                raise

    result, _ = await execute(SlowProvider(), limits=RuntimeLimits(timeout_seconds=0.01))

    assert result.termination_reason == TerminationReason.TIMEOUT
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_duplicate_tool_call_is_not_executed_twice() -> None:
    first = ToolCall(name="calculator", arguments={"expression": "2 + 2"})
    duplicate = ToolCall(name="calculator", arguments={"expression": "2 + 2"})
    provider = ScriptedProvider(
        [
            AgentDecision(action="tool", tool_call=first),
            AgentDecision(action="tool", tool_call=duplicate),
        ]
    )

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.INVALID_OUTPUT
    assert "duplicate" in result.error.lower()
    assert [event.type for event in events].count("tool.completed") == 1
    assert [event.type for event in events].count("tool.failed") == 1


@pytest.mark.asyncio
async def test_disabled_tool_hallucination_is_rejected_before_execution() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="not_enabled", arguments={}),
            )
        ]
    )

    result, events = await execute(provider)

    assert result.termination_reason == TerminationReason.INVALID_OUTPUT
    assert "disabled tool" in result.error
    assert all(event.type != "tool.started" for event in events)


@pytest.mark.asyncio
async def test_provider_failure_has_explicit_termination_reason() -> None:
    provider = ScriptedProvider([ProviderExecutionError("provider unavailable")])

    result, _ = await execute(provider)

    assert result.termination_reason == TerminationReason.PROVIDER_ERROR
    assert result.error == "provider unavailable"


@pytest.mark.asyncio
async def test_per_tool_call_limit_blocks_changed_arguments() -> None:
    provider = ScriptedProvider(
        [
            AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": f"{value} + 1"}),
            )
            for value in range(4)
        ]
    )

    result, events = await execute(
        provider, limits=RuntimeLimits(max_steps=4, max_calls_per_tool=3)
    )

    assert result.termination_reason == TerminationReason.INVALID_OUTPUT
    assert "per-run call limit" in result.error
    assert [event.type for event in events].count("tool.completed") == 3


@pytest.mark.asyncio
async def test_oversized_base_context_never_reaches_provider() -> None:
    provider = ScriptedProvider([AgentDecision(action="final", final_output="unreachable")])
    oversized_agent = definition()
    oversized_agent.instructions = "x" * 5_000

    result, _ = await execute(
        provider,
        limits=RuntimeLimits(max_context_chars=2_000),
        agent_definition=oversized_agent,
    )

    assert result.termination_reason == TerminationReason.INVALID_OUTPUT
    assert "context exceeds" in result.error
    assert provider.calls == 0
