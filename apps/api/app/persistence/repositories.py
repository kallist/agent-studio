from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import (
    AgentCreate,
    AgentDefinition,
    AgentEvent,
    RunKind,
    RunResult,
    RunStatus,
    RuntimeMode,
)
from app.domain.errors import EntityNotFoundError
from app.memory.contracts import MemoryRecord, MemorySettings
from app.memory.keys import normalized_memory_key
from app.memory.store import upsert_memory
from app.observability.redaction import redact_text, sanitize_event
from app.persistence.models import (
    AgentMemorySettingModel,
    AgentModel,
    MemoryModel,
    RunEventModel,
    RunModel,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_agent(model: AgentModel, *, memory_enabled: bool = True) -> AgentDefinition:
    return AgentDefinition(
        id=UUID(model.id),
        name=model.name,
        instructions=model.instructions,
        runtime_mode=RuntimeMode(model.runtime_mode),
        model=model.model,
        tools=json.loads(model.tools_json),
        knowledge_base_ids=[
            UUID(value) for value in json.loads(model.knowledge_base_ids_json or "[]")
        ],
        memory_enabled=memory_enabled,
        created_at=_aware(model.created_at),
    )


def to_run(model: RunModel) -> RunResult:
    return RunResult(
        id=UUID(model.id),
        agent_id=UUID(model.agent_id),
        status=RunStatus(model.status),
        run_kind=RunKind(model.run_kind),
        input=model.input,
        output=model.output,
        error=model.error,
        created_at=_aware(model.created_at),
        updated_at=_aware(model.updated_at),
    )


def to_event(model: RunEventModel) -> AgentEvent:
    stored = json.loads(model.payload_json)
    if isinstance(stored, dict) and stored.get("_trace_version") == 1:
        payload = stored.get("payload", {})
        correlation = {
            "step_index": stored.get("step_index"),
            "tool_call_id": stored.get("tool_call_id"),
            "duration_ms": stored.get("duration_ms"),
            "usage": stored.get("usage"),
        }
    else:
        payload = stored
        correlation = {}
    return AgentEvent(
        event_id=UUID(model.event_id),
        run_id=UUID(model.run_id),
        sequence=model.sequence,
        type=model.type,
        timestamp=_aware(model.timestamp),
        payload=payload,
        **correlation,
    )


def _agent_row_statement(agent_id: UUID, *, for_update: bool) -> Select[tuple[AgentModel]]:
    statement = select(AgentModel).where(AgentModel.id == str(agent_id))
    return statement.with_for_update() if for_update else statement


class Repositories:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_agent(self, data: AgentCreate) -> AgentDefinition:
        async with self._sessions() as session:
            model = AgentModel(
                name=data.name.strip(),
                instructions=data.instructions.strip(),
                runtime_mode=data.runtime_mode.value,
                model=data.model,
                tools_json=json.dumps(data.tools),
                knowledge_base_ids_json=json.dumps(
                    [str(value) for value in data.knowledge_base_ids]
                ),
                kind="normal",
            )
            session.add(model)
            await session.flush()
            session.add(
                AgentMemorySettingModel(
                    agent_id=model.id,
                    enabled=data.memory_enabled,
                )
            )
            await session.commit()
            await session.refresh(model)
            return to_agent(model, memory_enabled=data.memory_enabled)

    async def list_agents(self) -> list[AgentDefinition]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentModel)
                .where(AgentModel.kind == "normal")
                .order_by(AgentModel.created_at.desc())
            )
            agents = list(rows)
            settings = await session.scalars(select(AgentMemorySettingModel))
            enabled_by_agent = {row.agent_id: row.enabled for row in settings}
            return [
                to_agent(row, memory_enabled=enabled_by_agent.get(row.id, True)) for row in agents
            ]

    async def get_agent(self, agent_id: UUID) -> AgentDefinition:
        async with self._sessions() as session:
            model = await session.get(AgentModel, str(agent_id))
            if model is None:
                raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")
            setting = await session.get(AgentMemorySettingModel, str(agent_id))
            return to_agent(model, memory_enabled=setting.enabled if setting else True)

    async def get_public_agent(self, agent_id: UUID) -> AgentDefinition:
        async with self._sessions() as session:
            model = await session.get(AgentModel, str(agent_id))
            if model is None or model.kind != "normal":
                raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")
            setting = await session.get(AgentMemorySettingModel, str(agent_id))
            return to_agent(model, memory_enabled=setting.enabled if setting else True)

    async def validate_agent_run_kind(self, agent_id: UUID, run_kind: RunKind) -> None:
        async with self._sessions() as session:
            model = await session.get(AgentModel, str(agent_id))
            expected_kind = "evaluation" if run_kind is RunKind.EVALUATION else "normal"
            if model is None or model.kind != expected_kind:
                raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")

    async def set_memory_enabled(self, agent_id: UUID, enabled: bool) -> MemorySettings:
        async with self._serialized_agent_memory_transaction(agent_id) as (session, agent):
            if agent.kind != "normal":
                raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")
            setting = await session.get(AgentMemorySettingModel, str(agent_id))
            if setting is None:
                setting = AgentMemorySettingModel(agent_id=str(agent_id), enabled=enabled)
                session.add(setting)
            else:
                setting.enabled = enabled
        return MemorySettings(agent_id=agent_id, enabled=enabled)

    async def knowledge_bases_exist(self, knowledge_base_ids: list[UUID]) -> bool:
        if not knowledge_base_ids:
            return True
        from app.persistence.models import KnowledgeBaseModel

        async with self._sessions() as session:
            rows = await session.scalars(
                select(KnowledgeBaseModel.id).where(
                    KnowledgeBaseModel.id.in_([str(value) for value in knowledge_base_ids])
                )
            )
            return len(set(rows)) == len(set(knowledge_base_ids))

    async def create_evaluation_agent(self, source: AgentDefinition) -> AgentDefinition:
        async with self._sessions() as session:
            source_model = await session.get(AgentModel, str(source.id))
            if source_model is None or source_model.kind != "normal":
                raise EntityNotFoundError(f"Agent '{source.id}' was not found.")
            model = AgentModel(
                name=f"[Evaluation] {source.name}",
                instructions=source.instructions,
                runtime_mode=source.runtime_mode.value,
                model=source.model,
                tools_json=json.dumps(source.tools),
                knowledge_base_ids_json=json.dumps(
                    [str(value) for value in source.knowledge_base_ids]
                ),
                kind="evaluation",
                source_agent_id=str(source.id),
            )
            session.add(model)
            await session.flush()
            session.add(
                AgentMemorySettingModel(
                    agent_id=model.id,
                    enabled=source.memory_enabled,
                )
            )
            await session.commit()
            await session.refresh(model)
            return to_agent(model, memory_enabled=source.memory_enabled)

    async def create_run(
        self,
        agent_id: UUID,
        user_input: str,
        *,
        run_kind: RunKind = RunKind.NORMAL,
    ) -> RunResult:
        async with self._sessions() as session:
            model = RunModel(
                agent_id=str(agent_id),
                status=RunStatus.PENDING.value,
                run_kind=run_kind.value,
                input=user_input,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return to_run(model)

    async def get_run(self, run_id: UUID) -> RunResult:
        async with self._sessions() as session:
            model = await session.get(RunModel, str(run_id))
            if model is None:
                raise EntityNotFoundError(f"Run '{run_id}' was not found.")
            return to_run(model)

    async def list_runs(
        self,
        *,
        limit: int | None = None,
        run_kind: RunKind = RunKind.NORMAL,
    ) -> list[RunResult]:
        async with self._sessions() as session:
            statement = (
                select(RunModel)
                .where(RunModel.run_kind == run_kind.value)
                .order_by(RunModel.created_at.desc())
            )
            if limit is not None:
                statement = statement.limit(limit)
            rows = await session.scalars(statement)
            return [to_run(row) for row in rows]

    async def count_runs_by_status(
        self, *, run_kind: RunKind = RunKind.NORMAL
    ) -> dict[RunStatus, int]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(RunModel.status, func.count(RunModel.id))
                .where(RunModel.run_kind == run_kind.value)
                .group_by(RunModel.status)
            )
            return {RunStatus(status_value): count for status_value, count in rows.all()}

    async def update_run(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        output: str | None = None,
        error: str | None = None,
    ) -> RunResult:
        async with self._sessions() as session:
            model = await session.get(RunModel, str(run_id))
            if model is None:
                raise EntityNotFoundError(f"Run '{run_id}' was not found.")
            model.status = status.value
            model.output = output
            model.error = redact_text(error) if error is not None else None
            model.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(model)
            return to_run(model)

    async def append_event(self, event: AgentEvent) -> None:
        async with self._sessions() as session:
            session.add(_event_model(event))
            await session.commit()

    async def finish_run(
        self,
        run_id: UUID,
        status: RunStatus,
        event: AgentEvent,
        *,
        output: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            model = await session.get(RunModel, str(run_id))
            if model is None:
                raise EntityNotFoundError(f"Run '{run_id}' was not found.")
            model.status = status.value
            model.output = output
            model.error = redact_text(error) if error is not None else None
            model.updated_at = datetime.now(UTC)
            session.add(_event_model(event))
            await session.commit()

    async def finish_completed_run_with_memory(
        self,
        run_id: UUID,
        agent_id: UUID,
        terminal_event: AgentEvent,
        *,
        output: str,
        candidate: MemoryRecord,
    ) -> list[AgentEvent]:
        """Atomically gate/write memory, persist its event, and complete the run."""

        transaction_started = monotonic()
        async with self._serialized_agent_memory_transaction(agent_id) as (session, _agent):
            run = await session.get(RunModel, str(run_id))
            if run is None:
                raise EntityNotFoundError(f"Run '{run_id}' was not found.")
            if run.agent_id != str(agent_id):
                raise ValueError("Run and memory candidate belong to different agents.")

            setting = await session.get(AgentMemorySettingModel, str(agent_id))
            memory_enabled = setting.enabled if setting is not None else True
            existing_memory_id = await session.scalar(
                select(MemoryModel.id).where(
                    MemoryModel.agent_id == str(agent_id),
                    MemoryModel.normalized_key == normalized_memory_key(candidate.content),
                )
            )
            stored = await upsert_memory(session, candidate) if memory_enabled else None
            persisted_events: list[AgentEvent] = []
            terminal_sequence = terminal_event.sequence
            if stored is not None:
                memory_event = AgentEvent(
                    run_id=run_id,
                    sequence=terminal_event.sequence,
                    type="memory.written",
                    payload={
                        "memory_id": str(stored.id),
                        "importance": stored.importance,
                        "expires_at": (
                            stored.expires_at.isoformat()
                            if stored.expires_at is not None
                            else None
                        ),
                        "write_reason": stored.metadata.get("write_reason"),
                        "write_result": (
                            "deduplicated" if existing_memory_id is not None else "created"
                        ),
                    },
                )
                persisted_events.append(memory_event)
                terminal_sequence += 1

            terminal_duration = terminal_event.duration_ms
            if terminal_duration is not None:
                terminal_duration = round(
                    terminal_duration + (monotonic() - transaction_started) * 1000,
                    2,
                )
            normalized_terminal = terminal_event.model_copy(
                update={
                    "sequence": terminal_sequence,
                    "timestamp": datetime.now(UTC),
                    "duration_ms": terminal_duration,
                }
            )

            run.status = RunStatus.COMPLETED.value
            run.output = output
            run.error = None
            run.updated_at = datetime.now(UTC)
            for event in [*persisted_events, normalized_terminal]:
                session.add(_event_model(event))
            await session.flush()
            persisted_events.append(normalized_terminal)
            return persisted_events

    @asynccontextmanager
    async def _serialized_agent_memory_transaction(
        self, agent_id: UUID
    ) -> AsyncIterator[tuple[AsyncSession, AgentModel]]:
        """Serialize settings changes and finalization on one database-owned agent row."""

        async with self._sessions() as session:
            try:
                agent = await self._acquire_agent_memory_ownership(session, agent_id)
                yield session, agent
            except BaseException:
                await session.rollback()
                raise
            else:
                await session.commit()

    async def _acquire_agent_memory_ownership(
        self, session: AsyncSession, agent_id: UUID
    ) -> AgentModel:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            # SQLite has no row-level FOR UPDATE. BEGIN IMMEDIATE obtains the
            # database write reservation before the enabled flag is observed.
            await session.execute(text("BEGIN IMMEDIATE"))
            statement = _agent_row_statement(agent_id, for_update=False)
        elif dialect == "postgresql":
            # PostgreSQL holds this row lock until the surrounding transaction
            # commits, ordering finalization against settings updates.
            statement = _agent_row_statement(agent_id, for_update=True)
        else:
            raise RuntimeError(
                f"Agent memory serialization does not support database dialect '{dialect}'."
            )
        agent = await session.scalar(statement)
        if agent is None:
            raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")
        return agent

    async def list_events(self, run_id: UUID, after_sequence: int = 0) -> list[AgentEvent]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(RunEventModel)
                .where(
                    RunEventModel.run_id == str(run_id),
                    RunEventModel.sequence > after_sequence,
                )
                .order_by(RunEventModel.sequence)
            )
            return [to_event(row) for row in result]

    async def list_events_for_runs(self, run_ids: list[UUID]) -> dict[UUID, list[AgentEvent]]:
        grouped: dict[UUID, list[AgentEvent]] = {run_id: [] for run_id in run_ids}
        if not run_ids:
            return grouped
        async with self._sessions() as session:
            rows = await session.scalars(
                select(RunEventModel)
                .where(RunEventModel.run_id.in_([str(run_id) for run_id in run_ids]))
                .order_by(RunEventModel.run_id, RunEventModel.sequence)
            )
            for row in rows:
                event = to_event(row)
                grouped[event.run_id].append(event)
        return grouped

def _event_model(event: AgentEvent) -> RunEventModel:
    safe = sanitize_event(event)
    stored = {
        "_trace_version": 1,
        "step_index": safe.step_index,
        "tool_call_id": str(safe.tool_call_id) if safe.tool_call_id is not None else None,
        "duration_ms": safe.duration_ms,
        "usage": safe.usage.model_dump(mode="json") if safe.usage is not None else None,
        "payload": safe.payload,
    }
    return RunEventModel(
        event_id=str(safe.event_id),
        run_id=str(safe.run_id),
        sequence=safe.sequence,
        type=safe.type,
        timestamp=safe.timestamp,
        payload_json=json.dumps(stored, ensure_ascii=False),
    )
