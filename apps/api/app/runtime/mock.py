from __future__ import annotations

import re
from time import perf_counter

from app.domain.contracts import AgentEvent, EventSink, RuntimeInput, RuntimeOutput
from app.domain.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from app.tools.registry import ToolExecutor


class MockRuntime:
    """Deterministic rule-based runtime used by tests and the visible demo mode."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._tools = tools

    @property
    def is_configured(self) -> bool:
        return True

    async def run(self, runtime_input: RuntimeInput, emit: EventSink) -> RuntimeOutput:
        if "calculator" not in runtime_input.agent.tools:
            raise ToolNotFoundError("Calculator tool is not enabled for this agent.")
        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type="llm.started",
                payload={"summary": "分析输入并选择可用工具", "runtime": "mock"},
            )
        )
        expression = _extract_expression(runtime_input.user_input)
        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type="tool.selected",
                payload={"tool": "calculator", "reason": "输入包含算术表达式"},
            )
        )
        arguments = {"expression": expression}
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
        await emit(
            AgentEvent(
                run_id=runtime_input.run_id,
                sequence=0,
                type="llm.completed",
                payload={"summary": "已使用 calculator 完成计算"},
            )
        )
        return RuntimeOutput(final_output=result)


def _extract_expression(user_input: str) -> str:
    candidates = [part.strip() for part in re.findall(r"[0-9+\-*/().\s]+", user_input)]
    expressions = [part for part in candidates if any(char.isdigit() for char in part)]
    if not expressions:
        raise ToolValidationError("Mock runtime expected an arithmetic expression.")
    return max(expressions, key=len)
