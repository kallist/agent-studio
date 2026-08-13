from __future__ import annotations

from uuid import UUID

from app.memory.contracts import MemoryMatch, MemoryStore
from app.memory.policy import MemoryPolicy


class MemoryRetriever:
    def __init__(self, store: MemoryStore, policy: MemoryPolicy) -> None:
        self._store = store
        self._policy = policy

    async def retrieve(self, agent_id: UUID, query: str) -> list[MemoryMatch]:
        records = await self._store.list(agent_id)
        return self._policy.rank(query, records)
