from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.memory.contracts import RuntimeMemory


class RuntimeMode(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunKind(StrEnum):
    NORMAL = "normal"
    EVALUATION = "evaluation"


class IngestionState(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentPhase(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_MODEL = "waiting_for_model"
    EXECUTING_TOOL = "executing_tool"
    TERMINATED = "terminated"


class AgentState(BaseModel):
    phase: AgentPhase
    current_step: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TerminationReason(StrEnum):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    INVALID_OUTPUT = "invalid_output"


class ToolResultStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


KnownEventType = Literal[
    "run.started",
    "step.started",
    "llm.started",
    "llm.retrying",
    "llm.completed",
    "tool.selected",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "step.completed",
    "memory.retrieved",
    "memory.retrieval.skipped",
    "memory.written",
    "run.completed",
    "run.failed",
    "run.cancelled",
]

# Known names document the current contract; the actual type remains open so
# future application events survive persistence, SSE, and generic rendering.
EventType = str


class AgentDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    instructions: str
    runtime_mode: RuntimeMode
    model: str | None = None
    tools: list[str]
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    memory_enabled: bool = True
    created_at: datetime


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=8_000)
    runtime_mode: RuntimeMode = RuntimeMode.MOCK
    model: str | None = Field(default=None, max_length=120)
    tools: list[str] = Field(default_factory=lambda: ["calculator"], max_length=20)
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=20)
    memory_enabled: bool = True


class RunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)


class RunResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    status: RunStatus
    run_kind: RunKind = RunKind.NORMAL
    input: str
    output: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class UsageMetrics(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AgentEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: int
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_index: int | None = Field(default=None, ge=1)
    tool_call_id: UUID | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    usage: UsageMetrics | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolCallObservation(BaseModel):
    tool_call_id: UUID
    tool_name: str
    step_index: int | None = Field(default=None, ge=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    status: Literal["running", "completed", "failed", "unknown"]
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error_summary: str | None = None


class ToolCallCounts(BaseModel):
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)


class RunObservability(BaseModel):
    run_id: UUID
    agent_id: UUID
    runtime_type: str | None = None
    provider_type: str | None = None
    status: RunStatus
    termination_reason: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    terminal_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    event_count: int = Field(ge=0)
    step_count: int = Field(ge=0)
    tool_calls: ToolCallCounts
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    error_category: str | None = None
    error_summary: str | None = None
    event_statistics: dict[str, int] = Field(default_factory=dict)
    tools: list[ToolCallObservation] = Field(default_factory=list)


class DashboardObservability(BaseModel):
    total_runs: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    running: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)
    average_duration_ms: float | None = Field(default=None, ge=0)
    recent_runs: list[RunObservability] = Field(default_factory=list)


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_seconds: float
    permissions: list[str]


class ToolCall(BaseModel):
    call_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: UUID
    tool_name: str
    status: ToolResultStatus
    output: dict[str, JsonValue] | None = None
    error: str | None = None
    latency_ms: float = Field(ge=0)


class AgentDecision(BaseModel):
    action: Literal["final", "tool"]
    final_output: str | None = Field(default=None, max_length=20_000)
    tool_call: ToolCall | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> AgentDecision:
        if self.action == "final":
            if self.final_output is None or self.tool_call is not None:
                raise ValueError("A final decision requires only final_output.")
        elif self.tool_call is None or self.final_output is not None:
            raise ValueError("A tool decision requires only tool_call.")
        return self


class AgentStep(BaseModel):
    index: int = Field(ge=1)
    decision: AgentDecision
    tool_result: ToolResult | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentContext(BaseModel):
    instructions: str
    user_input: str
    tools: list[ToolSpec]
    steps: list[AgentStep]
    memory: RuntimeMemory = Field(default_factory=RuntimeMemory)
    omitted_steps: int = Field(default=0, ge=0)


class RuntimeLimits(BaseModel):
    max_steps: int = Field(default=8, ge=1, le=50)
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    invalid_output_retries: int = Field(default=1, ge=0, le=3)
    max_context_chars: int = Field(default=32_000, ge=2_000, le=200_000)
    max_decision_chars: int = Field(default=8_000, ge=500, le=50_000)
    max_calls_per_tool: int = Field(default=3, ge=1, le=20)


class RuntimeInput(BaseModel):
    run_id: UUID
    agent: AgentDefinition
    user_input: str
    granted_permissions: set[str] = Field(default_factory=lambda: {"compute"})
    limits: RuntimeLimits = Field(default_factory=RuntimeLimits)
    memory: RuntimeMemory = Field(default_factory=RuntimeMemory)


class AgentRun(BaseModel):
    run_id: UUID
    state: AgentState
    steps: list[AgentStep]
    termination_reason: TerminationReason
    final_output: str | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime


class EventSink(Protocol):
    async def __call__(self, event: AgentEvent) -> None: ...


class CancellationToken:
    """Cooperative cancellation signal shared by the service and runtime."""

    def __init__(self) -> None:
        import asyncio

        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


class AgentRuntime(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun: ...


class EventStream(Protocol):
    def subscribe(self, run_id: UUID, after_sequence: int = 0) -> AsyncIterator[AgentEvent]: ...


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)


class KnowledgeBaseView(BaseModel):
    id: UUID
    name: str
    description: str
    embedding_provider: str
    embedding_model: str
    created_at: datetime
    document_count: int = 0


class IngestionJobView(BaseModel):
    id: UUID
    document_id: UUID
    state: IngestionState
    error: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DocumentView(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    filename: str
    source: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    ingestion: IngestionJobView | None = None


class DocumentUploadAccepted(BaseModel):
    document: DocumentView
    ingestion_job: IngestionJobView


class RetrievalFilters(BaseModel):
    document_id: UUID | None = None
    source: str | None = Field(default=None, max_length=500)
    filename: str | None = Field(default=None, max_length=255)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: RetrievalFilters | None = None
    hybrid: bool = True


class KnowledgeCitation(BaseModel):
    document_id: UUID
    document: str
    chunk_id: UUID
    chunk_index: int
    source: str
    score: float
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query: str
    algorithm: Literal["semantic", "hybrid"]
    results: list[KnowledgeCitation]


class EmbeddingVector(BaseModel):
    chunk_id: UUID
    vector: list[float]
    provider: str
    model: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorMatch(BaseModel):
    chunk_id: UUID
    score: float


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def initialize(self) -> None: ...

    async def upsert(self, records: list[EmbeddingVector]) -> None: ...

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None: ...

    async def delete_document(self, document_id: UUID) -> None: ...

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[VectorMatch]: ...
