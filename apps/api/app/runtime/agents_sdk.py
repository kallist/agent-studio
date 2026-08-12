from __future__ import annotations

from time import perf_counter

from agents import Agent, RunConfig, Runner, function_tool, set_tracing_export_api_key

from app.domain.contracts import AgentEvent, EventSink, RuntimeInput, RuntimeOutput
from app.domain.errors import ProviderNotConfiguredError, ToolExecutionError
from app.runtime.providers import OpenAIProvider
from app.tools.registry import ToolExecutor


class AgentsSdkRuntime:
    """Translation boundary between application contracts and the OpenAI Agents SDK."""

    def __init__(self, provider: OpenAIProvider, tools: ToolExecutor) -> None:
        self._provider = provider
        self._tools = tools

    @property
    def is_configured(self) -> bool:
        return self._provider.is_configured

    async def run(self, runtime_input: RuntimeInput, emit: EventSink) -> RuntimeOutput:
        if not self.is_configured:
            raise ProviderNotConfiguredError("OpenAI provider is not configured.")
        if not self._provider.tracing_disabled and self._provider.api_key is not None:
            set_tracing_export_api_key(self._provider.api_key)

        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type="llm.started",
                payload={"summary": "OpenAI agent run started", "runtime": "openai"},
            )
        )

        @function_tool
        async def calculator(expression: str) -> str:
            """Safely evaluate arithmetic containing +, -, *, /, and parentheses."""
            arguments = {"expression": expression}
            await emit(
                AgentEvent(
                    run_id=runtime_input.run_id,
                    sequence=0,
                    type="tool.selected",
                    payload={"tool": "calculator", "reason": "Selected by OpenAI agent"},
                )
            )
            await emit(
                AgentEvent(
                    run_id=runtime_input.run_id,
                    sequence=0,
                    type="tool.started",
                    payload={"tool": "calculator", "arguments": arguments},
                )
            )
            started = perf_counter()
            try:
                result = await self._tools.execute("calculator", arguments)
            except ToolExecutionError as exc:
                await emit(
                    AgentEvent(
                        run_id=runtime_input.run_id,
                        sequence=0,
                        type="tool.failed",
                        payload={
                            "tool": "calculator",
                            "arguments": arguments,
                            "error": str(exc),
                            "latency_ms": round((perf_counter() - started) * 1000, 2),
                        },
                    )
                )
                raise
            await emit(
                AgentEvent(
                    run_id=runtime_input.run_id,
                    sequence=0,
                    type="tool.completed",
                    payload={
                        "tool": "calculator",
                        "arguments": arguments,
                        "result": result,
                        "latency_ms": round((perf_counter() - started) * 1000, 2),
                    },
                )
            )
            return result

        sdk_agent = Agent(
            name=runtime_input.agent.name,
            instructions=(
                f"{runtime_input.agent.instructions}\n"
                "Use the calculator tool for every arithmetic calculation. "
                "Return only the final result."
            ),
            model=self._provider.build_model(runtime_input.agent.model),
            tools=[calculator] if "calculator" in runtime_input.agent.tools else [],
        )
        result = await Runner.run(
            sdk_agent,
            runtime_input.user_input,
            run_config=RunConfig(tracing_disabled=self._provider.tracing_disabled),
        )
        final_output = str(result.final_output)
        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type="llm.completed",
                payload={"summary": "OpenAI agent run completed"},
            )
        )
        return RuntimeOutput(final_output=final_output)
