from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import (
    AgentCreate,
    AgentDefinition,
    AgentEvent,
    EventType,
    RunResult,
    RunStatus,
    RuntimeMode,
)
from app.domain.errors import EntityNotFoundError
from app.memory.contracts import MemoryRecord, MemorySettings
from app.memory.store import upsert_memory
from app.persistence.models import (
    AgentMemorySettingModel,
    AgentModel,
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
        input=model.input,
        output=model.output,
        error=model.error,
        created_at=_aware(model.created_at),
        updated_at=_aware(model.updated_at),
    )


def to_event(model: RunEventModel) -> AgentEvent:
    return AgentEvent(
        event_id=UUID(model.event_id),
        run_id=UUID(model.run_id),
        sequence=model.sequence,
        type=cast(EventType, model.type),
        timestamp=_aware(model.timestamp),
        payload=json.loads(model.payload_json),
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
            rows = await session.scalars(select(AgentModel).order_by(AgentModel.created_at.desc()))
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

    async def set_memory_enabled(self, agent_id: UUID, enabled: bool) -> MemorySettings:
        async with self._serialized_agent_memory_transaction(agent_id) as (session, _agent):
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

    async def create_run(self, agent_id: UUID, user_input: str) -> RunResult:
        async with self._sessions() as session:
            model = RunModel(
                agent_id=str(agent_id),
                status=RunStatus.PENDING.value,
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
            model.error = error
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
            model.error = error
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

        async with self._serialized_agent_memory_transaction(agent_id) as (session, _agent):
            run = await session.get(RunModel, str(run_id))
            if run is None:
                raise EntityNotFoundError(f"Run '{run_id}' was not found.")
            if run.agent_id != str(agent_id):
                raise ValueError("Run and memory candidate belong to different agents.")

            setting = await session.get(AgentMemorySettingModel, str(agent_id))
            memory_enabled = setting.enabled if setting is not None else True
            stored = await upsert_memory(session, candidate) if memory_enabled else None
            persisted_events: list[AgentEvent] = []
            normalized_terminal = terminal_event
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
                    },
                )
                persisted_events.append(memory_event)
                normalized_terminal = terminal_event.model_copy(
                    update={"sequence": terminal_event.sequence + 1}
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


def _event_model(event: AgentEvent) -> RunEventModel:
    return RunEventModel(
        event_id=str(event.event_id),
        run_id=str(event.run_id),
        sequence=event.sequence,
        type=event.type,
        timestamp=event.timestamp,
        payload_json=json.dumps(event.payload, ensure_ascii=False),
    )
