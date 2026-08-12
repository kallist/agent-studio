from __future__ import annotations

from app.domain.contracts import AgentRun, CancellationToken, EventSink, RuntimeInput
from app.runtime.engine import AgentLoop
from app.runtime.providers import MockProvider
from app.tools.registry import ToolExecutor


class MockRuntime:
    """Deterministic provider using the same bounded loop as production."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._loop = AgentLoop(MockProvider(), tools, runtime_name="mock")

    @property
    def is_configured(self) -> bool:
        return self._loop.is_configured

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun:
        return await self._loop.run(runtime_input, emit, cancellation)
