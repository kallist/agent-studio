from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from app.domain.contracts import (
    AgentCreate,
    AgentDefinition,
    AgentEvent,
    AgentRuntime,
    CancellationToken,
    RunRequest,
    RunResult,
    RunStatus,
    RuntimeInput,
    RuntimeMode,
    TerminationReason,
)
from app.domain.errors import AgentStudioError, ProviderNotConfiguredError
from app.persistence.repositories import Repositories

logger = logging.getLogger(__name__)


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[AgentEvent]]] = {}

    async def publish(self, event: AgentEvent) -> None:
        for queue in self._subscribers.get(event.run_id, set()):
            queue.put_nowait(event)

    def subscribe(self, run_id: UUID) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: UUID, queue: asyncio.Queue[AgentEvent]) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(run_id, None)


class AgentService:
    def __init__(
        self,
        repositories: Repositories,
        runtimes: dict[RuntimeMode, AgentRuntime],
        available_tools: set[str],
    ) -> None:
        self._repositories = repositories
        self._runtimes = runtimes
        self._available_tools = available_tools
        self._broker = EventBroker()
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancellations: dict[UUID, CancellationToken] = {}

    async def create_agent(self, request: AgentCreate) -> AgentDefinition:
        unknown = set(request.tools) - self._available_tools
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown tools: {names}")
        if request.knowledge_base_ids and "knowledge_search" not in request.tools:
            raise ValueError("knowledge_search must be enabled when knowledge bases are attached.")
        if "knowledge_search" in request.tools and not request.knowledge_base_ids:
            raise ValueError("knowledge_search requires at least one knowledge base.")
        if not await self._repositories.knowledge_bases_exist(request.knowledge_base_ids):
            raise ValueError("One or more knowledge bases do not exist.")
        return await self._repositories.create_agent(request)

    async def list_agents(self) -> list[AgentDefinition]:
        return await self._repositories.list_agents()

    async def get_agent(self, agent_id: UUID) -> AgentDefinition:
        return await self._repositories.get_agent(agent_id)

    async def create_run(self, agent_id: UUID, request: RunRequest) -> RunResult:
        agent = await self._repositories.get_agent(agent_id)
        runtime = self._runtimes[agent.runtime_mode]
        if not runtime.is_configured:
            raise ProviderNotConfiguredError("OpenAI provider is not configured.")
        run = await self._repositories.create_run(agent_id, request.input)
        cancellation = CancellationToken()
        self._cancellations[run.id] = cancellation
        task = asyncio.create_task(self._execute(run, agent, runtime, cancellation))
        self._tasks[run.id] = task

        def cleanup(completed: asyncio.Task[None]) -> None:
            self._cleanup(run.id, completed)

        task.add_done_callback(cleanup)
        return run

    def _cleanup(self, run_id: UUID, task: asyncio.Task[None]) -> None:
        self._tasks.pop(run_id, None)
        self._cancellations.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent run task escaped its error boundary.",
                exc_info=task.exception(),
                extra={"run_id": str(run_id)},
            )

    async def _execute(
        self,
        run: RunResult,
        agent: AgentDefinition,
        runtime: AgentRuntime,
        cancellation: CancellationToken,
    ) -> None:
        sequence = 0

        async def emit(event: AgentEvent) -> None:
            nonlocal sequence
            sequence += 1
            normalized = event.model_copy(update={"sequence": sequence})
            await self._repositories.append_event(normalized)
            await self._broker.publish(normalized)

        async def finish(
            status: RunStatus,
            event: AgentEvent,
            *,
            output: str | None = None,
            error: str | None = None,
        ) -> None:
            nonlocal sequence
            sequence += 1
            normalized = event.model_copy(update={"sequence": sequence})
            await self._repositories.finish_run(
                run.id,
                status,
                normalized,
                output=output,
                error=error,
            )
            await self._broker.publish(normalized)

        await self._repositories.update_run(run.id, RunStatus.RUNNING)
        await emit(
            AgentEvent(
                run_id=run.id,
                sequence=0,
                type="run.started",
                payload={"agent_id": str(agent.id), "runtime": agent.runtime_mode.value},
            )
        )
        try:
            granted_permissions = {"compute"}
            if "knowledge_search" in agent.tools and agent.knowledge_base_ids:
                granted_permissions.add("knowledge:read")
            output = await runtime.run(
                RuntimeInput(
                    run_id=run.id,
                    agent=agent,
                    user_input=run.input,
                    granted_permissions=granted_permissions,
                ),
                emit,
                cancellation,
            )
        except AgentStudioError as exc:
            message = str(exc)
            await finish(
                RunStatus.FAILED,
                AgentEvent(
                    run_id=run.id,
                    sequence=0,
                    type="run.failed",
                    payload={"error": message},
                ),
                error=message,
            )
        except Exception:
            logger.exception("Unexpected agent runtime failure.", extra={"run_id": str(run.id)})
            message = "Agent runtime failed unexpectedly."
            await finish(
                RunStatus.FAILED,
                AgentEvent(
                    run_id=run.id,
                    sequence=0,
                    type="run.failed",
                    payload={"error": message},
                ),
                error=message,
            )
        else:
            terminal_payload = {
                "termination_reason": output.termination_reason.value,
                "steps": len(output.steps),
            }
            if output.termination_reason == TerminationReason.COMPLETED:
                final_output = output.final_output or ""
                terminal_payload["final_output"] = final_output
                await finish(
                    RunStatus.COMPLETED,
                    AgentEvent(
                        run_id=run.id,
                        sequence=0,
                        type="run.completed",
                        payload=terminal_payload,
                    ),
                    output=final_output,
                )
                return
            if output.termination_reason == TerminationReason.CANCELLED:
                terminal_payload["error"] = output.error or "Agent run was cancelled."
                await finish(
                    RunStatus.CANCELLED,
                    AgentEvent(
                        run_id=run.id,
                        sequence=0,
                        type="run.cancelled",
                        payload=terminal_payload,
                    ),
                    error=output.error,
                )
                return
            message = output.error or f"Agent terminated: {output.termination_reason.value}."
            terminal_payload["error"] = message
            await finish(
                RunStatus.FAILED,
                AgentEvent(
                    run_id=run.id,
                    sequence=0,
                    type="run.failed",
                    payload=terminal_payload,
                ),
                error=message,
            )

    async def cancel_run(self, run_id: UUID) -> RunResult:
        run = await self._repositories.get_run(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        cancellation = self._cancellations.get(run_id)
        if cancellation is None:
            raise AgentStudioError("Run is not active in this process and cannot be cancelled.")
        cancellation.cancel()
        return run

    async def get_run(self, run_id: UUID) -> RunResult:
        return await self._repositories.get_run(run_id)

    async def list_events(self, run_id: UUID) -> list[AgentEvent]:
        await self._repositories.get_run(run_id)
        return await self._repositories.list_events(run_id)

    async def stream_events(
        self, run_id: UUID, after_sequence: int = 0
    ) -> AsyncIterator[AgentEvent]:
        queue = self._broker.subscribe(run_id)
        cursor = after_sequence
        try:
            events = await self._repositories.list_events(run_id, cursor)
            for event in events:
                cursor = event.sequence
                yield event
            run = await self._repositories.get_run(run_id)
            if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return
            while True:
                event = await queue.get()
                if event.sequence <= cursor:
                    continue
                cursor = event.sequence
                yield event
                if event.type in {"run.completed", "run.failed", "run.cancelled"}:
                    return
        finally:
            self._broker.unsubscribe(run_id, queue)
