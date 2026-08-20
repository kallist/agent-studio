from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from app.domain.contracts import (
    AgentCreate,
    AgentDefinition,
    AgentEvent,
    AgentRuntime,
    CancellationToken,
    DashboardObservability,
    RunKind,
    RunObservability,
    RunRequest,
    RunResult,
    RunStatus,
    RuntimeInput,
    RuntimeMode,
    TerminationReason,
)
from app.domain.errors import AgentStudioError, EntityNotFoundError, ProviderNotConfiguredError
from app.memory.contracts import (
    MemoryKind,
    MemoryRecord,
    MemorySettings,
    MemoryStore,
    RuntimeMemory,
)
from app.memory.policy import MemoryPolicy
from app.memory.retriever import MemoryRetriever
from app.observability.aggregation import aggregate_dashboard, aggregate_run
from app.observability.redaction import sanitize_event
from app.persistence.repositories import Repositories

logger = logging.getLogger(__name__)


class EventBroker:
    _QUEUE_SIZE = 256

    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[AgentEvent]]] = {}

    async def publish(self, event: AgentEvent) -> None:
        for queue in self._subscribers.get(event.run_id, set()):
            if not queue.full():
                queue.put_nowait(event)

    def subscribe(self, run_id: UUID) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._QUEUE_SIZE)
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
        memory_store: MemoryStore,
        memory_retriever: MemoryRetriever,
        memory_policy: MemoryPolicy,
    ) -> None:
        self._repositories = repositories
        self._runtimes = runtimes
        self._available_tools = available_tools
        self._memory_store = memory_store
        self._memory_retriever = memory_retriever
        self._memory_policy = memory_policy
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

    async def get_public_agent(self, agent_id: UUID) -> AgentDefinition:
        return await self._repositories.get_public_agent(agent_id)

    async def set_memory_enabled(self, agent_id: UUID, enabled: bool) -> MemorySettings:
        return await self._repositories.set_memory_enabled(agent_id, enabled)

    async def list_memories(self, agent_id: UUID) -> list[MemoryRecord]:
        await self._repositories.get_public_agent(agent_id)
        return await self._memory_store.list(agent_id)

    async def delete_memory(self, agent_id: UUID, memory_id: UUID) -> None:
        await self._repositories.get_public_agent(agent_id)
        deleted = await self._memory_store.delete(agent_id, memory_id)
        if not deleted:
            raise EntityNotFoundError(f"Memory '{memory_id}' was not found for this agent.")

    async def create_run(
        self,
        agent_id: UUID,
        request: RunRequest,
        *,
        run_kind: RunKind = RunKind.NORMAL,
    ) -> RunResult:
        agent = await self._repositories.get_agent(agent_id)
        await self._repositories.validate_agent_run_kind(agent_id, run_kind)
        runtime = self._runtimes[agent.runtime_mode]
        if not runtime.is_configured:
            raise ProviderNotConfiguredError("OpenAI provider is not configured.")
        run = await self._repositories.create_run(
            agent_id, request.input, run_kind=run_kind
        )
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
        loop = asyncio.get_running_loop()
        run_started_clock = loop.time()

        async def emit(event: AgentEvent) -> None:
            nonlocal sequence
            sequence += 1
            normalized = sanitize_event(event.model_copy(update={"sequence": sequence}))
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
            duration_ms = event.duration_ms
            if event.type in {"run.completed", "run.failed", "run.cancelled"}:
                duration_ms = round((loop.time() - run_started_clock) * 1000, 2)
            normalized = sanitize_event(
                event.model_copy(
                    update={"sequence": sequence, "duration_ms": duration_ms}
                )
            )
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
                payload={
                    "agent_id": str(agent.id),
                    "runtime": agent.runtime_mode.value,
                    "provider": agent.runtime_mode.value,
                },
            )
        )
        try:
            granted_permissions = {"compute"}
            if "knowledge_search" in agent.tools and agent.knowledge_base_ids:
                granted_permissions.add("knowledge:read")
            timestamp = datetime.now(UTC)
            runtime_memory = RuntimeMemory(
                conversation=[
                    MemoryRecord(
                        agent_id=agent.id,
                        kind=MemoryKind.CONVERSATION,
                        content=run.input,
                        importance=0,
                        source_run_id=run.id,
                        created_at=timestamp,
                        metadata={"role": "user"},
                    )
                ]
            )
            if agent.memory_enabled:
                retrieval_started = loop.time()
                runtime_memory.long_term = await self._memory_retriever.retrieve(
                    agent.id, run.input
                )
                retrieval_duration_ms = round((loop.time() - retrieval_started) * 1000, 2)
                if runtime_memory.long_term:
                    await emit(
                        AgentEvent(
                            run_id=run.id,
                            sequence=0,
                            type="memory.retrieved",
                            duration_ms=retrieval_duration_ms,
                            payload={
                                "count": len(runtime_memory.long_term),
                                "outcome": "retrieved",
                                "context_budget_chars": self._memory_policy.max_context_chars,
                                "matches": [
                                    {
                                        "memory_id": str(match.record.id),
                                        "score": match.score,
                                        "relevance": match.relevance,
                                        "recency": match.recency,
                                        "importance": match.importance,
                                    }
                                    for match in runtime_memory.long_term
                                ],
                            },
                        )
                    )
                else:
                    await emit(
                        AgentEvent(
                            run_id=run.id,
                            sequence=0,
                            type="memory.retrieval.skipped",
                            duration_ms=retrieval_duration_ms,
                            payload={
                                "count": 0,
                                "reason": "no_match_or_threshold",
                                "context_budget_chars": self._memory_policy.max_context_chars,
                            },
                        )
                    )
            else:
                await emit(
                    AgentEvent(
                        run_id=run.id,
                        sequence=0,
                        type="memory.retrieval.skipped",
                        payload={"count": 0, "reason": "disabled"},
                    )
                )
            output = await runtime.run(
                RuntimeInput(
                    run_id=run.id,
                    agent=agent,
                    user_input=run.input,
                    granted_permissions=granted_permissions,
                    memory=runtime_memory,
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
                    payload={"error": message, "error_category": "application_error"},
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
                    payload={"error": message, "error_category": "unexpected_error"},
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
                candidate = self._memory_policy.propose_write(
                    agent_id=agent.id,
                    run_id=run.id,
                    user_input=run.input,
                )
                if candidate is not None:
                    try:
                        committed_events = (
                            await self._repositories.finish_completed_run_with_memory(
                                run.id,
                                agent.id,
                                AgentEvent(
                                    run_id=run.id,
                                    sequence=sequence + 1,
                                    type="run.completed",
                                    duration_ms=round(
                                        (loop.time() - run_started_clock) * 1000, 2
                                    ),
                                    payload=terminal_payload,
                                ),
                                output=final_output,
                                candidate=candidate,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Atomic memory/run completion failed.",
                            extra={"run_id": str(run.id)},
                        )
                        message = "Run completion could not be persisted."
                        await finish(
                            RunStatus.FAILED,
                            AgentEvent(
                                run_id=run.id,
                                sequence=0,
                                type="run.failed",
                                payload={
                                    "error": message,
                                    "error_category": "persistence_error",
                                },
                            ),
                            error=message,
                        )
                        return
                    sequence = committed_events[-1].sequence
                    for committed_event in committed_events:
                        await self._broker.publish(sanitize_event(committed_event))
                    return
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
                terminal_payload["error_category"] = "cancelled"
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
            terminal_payload["error_category"] = output.termination_reason.value
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

    async def wait_for_terminal(self, run_id: UUID) -> RunResult:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)
        return await self._repositories.get_run(run_id)

    async def fail_interrupted_run(self, run_id: UUID) -> RunResult:
        run = await self._repositories.get_run(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        events = await self._repositories.list_events(run_id)
        sequence = max((event.sequence for event in events), default=0) + 1
        message = "Agent run was interrupted by process restart."
        await self._repositories.finish_run(
            run_id,
            RunStatus.FAILED,
            AgentEvent(
                run_id=run_id,
                sequence=sequence,
                type="run.failed",
                payload={
                    "error": message,
                    "error_category": "process_restart",
                    "termination_reason": "provider_error",
                },
            ),
            error=message,
        )
        return await self._repositories.get_run(run_id)

    async def list_events(self, run_id: UUID) -> list[AgentEvent]:
        await self._repositories.get_run(run_id)
        return await self._repositories.list_events(run_id)

    async def get_run_observability(self, run_id: UUID) -> RunObservability:
        run = await self._repositories.get_run(run_id)
        events = await self._repositories.list_events(run_id)
        return aggregate_run(run, events)

    async def get_dashboard_observability(self) -> DashboardObservability:
        recent_runs = await self._repositories.list_runs(limit=30)
        recent_events = await self._repositories.list_events_for_runs(
            [run.id for run in recent_runs]
        )
        status_counts = await self._repositories.count_runs_by_status()
        return aggregate_dashboard(
            recent_runs,
            recent_events,
            status_counts=status_counts,
        )

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
                await queue.get()
                # The queue is only a bounded wake-up signal. Persistence is the
                # source of truth, so a slow subscriber catches up without an
                # unbounded in-memory backlog or dropped events.
                events = await self._repositories.list_events(run_id, cursor)
                for event in events:
                    cursor = event.sequence
                    yield event
                    if event.type in {"run.completed", "run.failed", "run.cancelled"}:
                        return
        finally:
            self._broker.unsubscribe(run_id, queue)
