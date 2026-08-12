from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class RuntimeMode(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


EventType = Literal[
    "run.started",
    "llm.started",
    "llm.completed",
    "tool.selected",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "run.completed",
    "run.failed",
]


class AgentDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    instructions: str
    runtime_mode: RuntimeMode
    model: str | None = None
    tools: list[str]
    created_at: datetime


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=8_000)
    runtime_mode: RuntimeMode = RuntimeMode.MOCK
    model: str | None = Field(default=None, max_length=120)
    tools: list[str] = Field(default_factory=lambda: ["calculator"], max_length=20)


class RunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)


class RunResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    status: RunStatus
    input: str
    output: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: int
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeInput(BaseModel):
    run_id: UUID
    agent: AgentDefinition
    user_input: str


class RuntimeOutput(BaseModel):
    final_output: str


class EventSink(Protocol):
    async def __call__(self, event: AgentEvent) -> None: ...


class AgentRuntime(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def run(self, runtime_input: RuntimeInput, emit: EventSink) -> RuntimeOutput: ...


class EventStream(Protocol):
    def subscribe(self, run_id: UUID, after_sequence: int = 0) -> AsyncIterator[AgentEvent]: ...
