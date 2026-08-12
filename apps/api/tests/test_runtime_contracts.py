from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from agents import Agent, RunConfig, Runner

from app.domain.contracts import (
    AgentDecision,
    AgentDefinition,
    AgentEvent,
    AgentRuntime,
    RuntimeInput,
    RuntimeMode,
    TerminationReason,
    ToolCall,
)
from app.domain.errors import ProviderNotConfiguredError
from app.runtime.agents_sdk import AgentsSdkRuntime
from app.runtime.mock import MockRuntime
from app.runtime.providers import OpenAIProvider
from app.tools.registry import ToolExecutor, default_tool_registry


def agent(runtime_mode: RuntimeMode) -> AgentDefinition:
    return AgentDefinition(
        id=uuid4(),
        name="Calculator Agent",
        instructions="Use the calculator.",
        runtime_mode=runtime_mode,
        model=None,
        tools=["calculator"],
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_mock_runtime_emits_application_contract_and_result() -> None:
    runtime: AgentRuntime = MockRuntime(ToolExecutor(default_tool_registry()))
    run_id = uuid4()
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    result = await runtime.run(
        RuntimeInput(
            run_id=run_id,
            agent=agent(RuntimeMode.MOCK),
            user_input="计算 128 * 37 + 456",
        ),
        collect,
    )

    assert result.final_output == "5192"
    assert result.termination_reason == TerminationReason.COMPLETED
    assert len(result.steps) == 2
    assert [event.type for event in events] == [
        "step.started",
        "llm.started",
        "llm.completed",
        "tool.selected",
        "tool.started",
        "tool.completed",
        "step.completed",
        "step.started",
        "llm.started",
        "llm.completed",
        "step.completed",
    ]
    assert events[5].payload["result"] == {"result": "5192"}


@pytest.mark.asyncio
async def test_agents_sdk_adapter_has_same_port_and_clear_credential_gate() -> None:
    runtime = AgentsSdkRuntime(
        OpenAIProvider(api_key=None, default_model="gpt-5.6-terra"),
        ToolExecutor(default_tool_registry()),
    )
    typed_runtime = cast(AgentRuntime, runtime)

    with pytest.raises(ProviderNotConfiguredError, match="not configured"):
        await typed_runtime.run(
            RuntimeInput(
                run_id=uuid4(),
                agent=agent(RuntimeMode.OPENAI),
                user_input="计算 1 + 1",
            ),
            _ignore_event,
        )


async def _ignore_event(event: AgentEvent) -> None:
    del event


@pytest.mark.asyncio
async def test_agents_sdk_adapter_uses_typed_decisions_and_application_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_agents: list[Agent[object]] = []

    async def fake_run(
        starting_agent: Agent[object],
        user_input: str,
        *,
        max_turns: int,
        run_config: RunConfig,
    ) -> SimpleNamespace:
        captured_agents.append(starting_agent)
        context = json.loads(user_input)
        assert max_turns == 1
        assert run_config.tracing_disabled is True
        assert starting_agent.output_type is AgentDecision
        assert starting_agent.tools == []
        if not context["steps"]:
            return SimpleNamespace(
                final_output=AgentDecision(
                    action="tool",
                    tool_call=ToolCall(
                        name="calculator", arguments={"expression": "128 * 37 + 456"}
                    ),
                )
            )
        return SimpleNamespace(final_output=AgentDecision(action="final", final_output="5192"))

    monkeypatch.setattr(Runner, "run", fake_run)
    runtime = AgentsSdkRuntime(
        OpenAIProvider(api_key="test", default_model="gpt-5.6-terra"),
        ToolExecutor(default_tool_registry()),
    )
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    result = await runtime.run(
        RuntimeInput(
            run_id=uuid4(),
            agent=agent(RuntimeMode.OPENAI),
            user_input="计算 128 * 37 + 456",
        ),
        collect,
    )

    assert len(captured_agents) == 2
    assert result.final_output == "5192"
    assert result.termination_reason == TerminationReason.COMPLETED
    assert [event.type for event in events].count("tool.completed") == 1
