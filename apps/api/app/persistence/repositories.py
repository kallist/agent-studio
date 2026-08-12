from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
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
from app.persistence.models import AgentModel, RunEventModel, RunModel


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_agent(model: AgentModel) -> AgentDefinition:
    return AgentDefinition(
        id=UUID(model.id),
        name=model.name,
        instructions=model.instructions,
        runtime_mode=RuntimeMode(model.runtime_mode),
        model=model.model,
        tools=json.loads(model.tools_json),
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
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return to_agent(model)

    async def list_agents(self) -> list[AgentDefinition]:
        async with self._sessions() as session:
            rows = await session.scalars(select(AgentModel).order_by(AgentModel.created_at.desc()))
            return [to_agent(row) for row in rows]

    async def get_agent(self, agent_id: UUID) -> AgentDefinition:
        async with self._sessions() as session:
            model = await session.get(AgentModel, str(agent_id))
            if model is None:
                raise EntityNotFoundError(f"Agent '{agent_id}' was not found.")
            return to_agent(model)

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
