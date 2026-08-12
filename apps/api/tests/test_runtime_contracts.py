from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from agents import Agent, RunConfig, Runner
from agents.tool_context import ToolContext

from app.domain.contracts import (
    AgentDefinition,
    AgentEvent,
    AgentRuntime,
    RuntimeInput,
    RuntimeMode,
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
    assert [event.type for event in events] == [
        "llm.started",
        "tool.selected",
        "tool.started",
        "tool.completed",
        "llm.completed",
    ]
    assert events[3].payload["result"] == "5192"


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
            lambda event: _ignore_event(event),
        )


async def _ignore_event(event: AgentEvent) -> None:
    del event


@pytest.mark.asyncio
async def test_agents_sdk_adapter_maps_tool_lifecycle_to_application_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_agent: Agent[object] | None = None

    async def fake_run(
        starting_agent: Agent[object],
        user_input: str,
        *,
        run_config: RunConfig,
    ) -> SimpleNamespace:
        nonlocal captured_agent
        captured_agent = starting_agent
        assert user_input == "计算 128 * 37 + 456"
        assert run_config.tracing_disabled is True
        tool = starting_agent.tools[0]
        arguments = '{"expression":"128 * 37 + 456"}'
        context = ToolContext(
            context=None,
            tool_name="calculator",
            tool_call_id="call-1",
            tool_arguments=arguments,
            run_config=run_config,
        )
        output = await tool.on_invoke_tool(context, arguments)
        return SimpleNamespace(final_output=output)

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

    assert captured_agent is not None
    assert result.final_output == "5192"
    assert [event.type for event in events] == [
        "llm.started",
        "tool.selected",
        "tool.started",
        "tool.completed",
        "llm.completed",
    ]
    assert events[3].payload["result"] == "5192"
