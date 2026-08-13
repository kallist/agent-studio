from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MemoryKind(StrEnum):
    CONVERSATION = "conversation"
    WORKING = "working"
    LONG_TERM = "long_term"


class MemoryRecord(BaseModel):
    """One common shape for ephemeral and durable memory."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=2_000)
    importance: float = Field(ge=0, le=1)
    source_run_id: UUID | None = None
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryMatch(BaseModel):
    record: MemoryRecord
    score: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)


class RuntimeMemory(BaseModel):
    """Memory snapshot scoped to one runtime invocation."""

    conversation: list[MemoryRecord] = Field(default_factory=list)
    working: list[MemoryRecord] = Field(default_factory=list)
    long_term: list[MemoryMatch] = Field(default_factory=list)


class MemorySettings(BaseModel):
    agent_id: UUID
    enabled: bool


class MemorySettingsUpdate(BaseModel):
    enabled: bool


class MemoryStore(Protocol):
    async def write(self, record: MemoryRecord) -> MemoryRecord: ...

    async def list(self, agent_id: UUID) -> list[MemoryRecord]: ...

    async def delete(self, agent_id: UUID, memory_id: UUID) -> bool: ...

    async def purge_expired(self, now: datetime) -> int: ...
