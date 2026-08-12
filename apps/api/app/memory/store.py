from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.memory.contracts import MemoryKind, MemoryRecord
from app.persistence.models import MemoryModel


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_record(model: MemoryModel) -> MemoryRecord:
    return MemoryRecord(
        id=UUID(model.id),
        agent_id=UUID(model.agent_id),
        kind=MemoryKind(model.kind),
        content=model.content,
        importance=model.importance,
        source_run_id=UUID(model.source_run_id) if model.source_run_id else None,
        created_at=_aware(model.created_at),
        expires_at=_aware(model.expires_at) if model.expires_at else None,
        metadata=json.loads(model.metadata_json),
    )


class SqlAlchemyMemoryStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def write(self, record: MemoryRecord) -> MemoryRecord:
        if record.kind is not MemoryKind.LONG_TERM:
            raise ValueError("Only long-term memory can be persisted.")
        async with self._sessions() as session:
            existing = await session.scalar(
                select(MemoryModel).where(
                    MemoryModel.agent_id == str(record.agent_id),
                    func.lower(MemoryModel.content) == record.content.casefold(),
                    MemoryModel.expires_at > record.created_at,
                )
            )
            if existing is not None:
                existing.importance = max(existing.importance, record.importance)
                existing.expires_at = record.expires_at
                existing.source_run_id = (
                    str(record.source_run_id) if record.source_run_id is not None else None
                )
                await session.commit()
                await session.refresh(existing)
                return _to_record(existing)

            model = MemoryModel(
                id=str(record.id),
                agent_id=str(record.agent_id),
                source_run_id=(
                    str(record.source_run_id) if record.source_run_id is not None else None
                ),
                kind=record.kind.value,
                content=record.content,
                importance=record.importance,
                created_at=record.created_at,
                expires_at=record.expires_at,
                metadata_json=json.dumps(record.metadata, ensure_ascii=False),
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _to_record(model)

    async def list(self, agent_id: UUID) -> list[MemoryRecord]:
        now = datetime.now(UTC)
        await self.purge_expired(now)
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MemoryModel)
                .where(MemoryModel.agent_id == str(agent_id))
                .order_by(MemoryModel.created_at.desc())
            )
            return [_to_record(row) for row in rows]

    async def delete(self, agent_id: UUID, memory_id: UUID) -> bool:
        async with self._sessions() as session:
            model = await session.scalar(
                select(MemoryModel).where(
                    MemoryModel.id == str(memory_id),
                    MemoryModel.agent_id == str(agent_id),
                )
            )
            if model is None:
                return False
            await session.delete(model)
            await session.commit()
            return True

    async def purge_expired(self, now: datetime) -> int:
        async with self._sessions() as session:
            expired_ids = list(
                await session.scalars(select(MemoryModel.id).where(MemoryModel.expires_at <= now))
            )
            if not expired_ids:
                return 0
            await session.execute(delete(MemoryModel).where(MemoryModel.expires_at <= now))
            await session.commit()
            return len(expired_ids)
