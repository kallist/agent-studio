from __future__ import annotations

from app.domain.contracts import AgentRun, CancellationToken, EventSink, RuntimeInput
from app.runtime.engine import AgentLoop
from app.runtime.providers import MockProvider
from app.tools.knowledge_search import bind_knowledge_bases
from app.tools.registry import ToolExecutor


class MockRuntime:
    """Deterministic provider using the same bounded loop as production."""

    def __init__(self, tools: ToolExecutor, *, blocking_input: str | None = None) -> None:
        self._loop = AgentLoop(
            MockProvider(blocking_input=blocking_input), tools, runtime_name="mock"
        )

    @property
    def is_configured(self) -> bool:
        return self._loop.is_configured

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun:
        with bind_knowledge_bases(runtime_input.agent.knowledge_base_ids):
            return await self._loop.run(runtime_input, emit, cancellation)
