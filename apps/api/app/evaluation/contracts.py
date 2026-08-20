from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

from app.domain.contracts import RunStatus


class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationCaseStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class GraderOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class GraderType(StrEnum):
    RUN_STATUS = "run_status"
    FINAL_OUTPUT_NON_EMPTY = "final_output_non_empty"
    EXACT_MATCH = "exact_match"
    CONTAINS = "contains"
    TOOL_SELECTED = "tool_selected"
    TOOL_NOT_SELECTED = "tool_not_selected"
    RETRIEVAL_HIT = "retrieval_hit"
    CITATION = "citation"
    MEMORY_RETRIEVED = "memory_retrieved"
    MAX_STEPS = "max_steps"
    MAX_DURATION = "max_duration"


class EvaluationMemorySeed(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    importance: float = Field(default=0.9, ge=0, le=1)


class EvaluationCaseSetup(BaseModel):
    memories: list[EvaluationMemorySeed] = Field(default_factory=list, max_length=10)


class GraderConfig(BaseModel):
    type: GraderType
    required: bool = True
    value: str | None = Field(default=None, max_length=20_000)
    case_sensitive: bool = True
    tool_name: str | None = Field(default=None, min_length=1, max_length=120)
    expected_source: str | None = Field(default=None, min_length=1, max_length=500)
    expected_document_id: UUID | None = None
    expected_status: RunStatus | None = None
    maximum: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_configuration(self) -> GraderConfig:
        if self.type in {GraderType.EXACT_MATCH, GraderType.CONTAINS} and self.value is None:
            raise ValueError(f"{self.type.value} requires value.")
        if self.type in {GraderType.TOOL_SELECTED, GraderType.TOOL_NOT_SELECTED}:
            if self.tool_name is None:
                raise ValueError(f"{self.type.value} requires tool_name.")
        if self.type in {GraderType.MAX_STEPS, GraderType.MAX_DURATION}:
            if self.maximum is None:
                raise ValueError(f"{self.type.value} requires maximum.")
        if self.type == GraderType.MAX_STEPS and self.maximum is not None:
            if not self.maximum.is_integer():
                raise ValueError("max_steps maximum must be an integer.")
        return self


class EvaluationCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    input: str = Field(min_length=1, max_length=20_000)
    enabled: bool = True
    graders: list[GraderConfig] = Field(min_length=1, max_length=30)
    setup: EvaluationCaseSetup = Field(default_factory=EvaluationCaseSetup)


class EvaluationCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    input: str | None = Field(default=None, min_length=1, max_length=20_000)
    enabled: bool | None = None
    graders: list[GraderConfig] | None = Field(default=None, min_length=1, max_length=30)
    setup: EvaluationCaseSetup | None = None


class EvaluationCaseView(EvaluationCaseCreate):
    id: UUID
    suite_id: UUID
    position: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class EvaluationSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)
    agent_id: UUID
    cases: list[EvaluationCaseCreate] = Field(default_factory=list, max_length=200)


class EvaluationSuiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2_000)
    agent_id: UUID | None = None


class EvaluationSuiteSummary(BaseModel):
    id: UUID
    name: str
    description: str
    agent_id: UUID
    revision: int = Field(ge=1)
    case_count: int = Field(ge=0)
    last_run_id: UUID | None = None
    last_run_status: EvaluationRunStatus | None = None
    last_pass_rate: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime
    updated_at: datetime


class EvaluationSuiteView(EvaluationSuiteSummary):
    cases: list[EvaluationCaseView] = Field(default_factory=list)


class GraderMetric(BaseModel):
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)


class EvaluationRunView(BaseModel):
    id: UUID
    suite_id: UUID
    agent_id: UUID
    status: EvaluationRunStatus
    suite_revision: int = Field(ge=1)
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    error_cases: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    average_duration_ms: float | None = Field(default=None, ge=0)
    p95_duration_ms: float | None = Field(default=None, ge=0)
    grader_metrics: dict[str, GraderMetric] = Field(default_factory=dict)
    cancel_requested: bool = False
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GraderResultDraft(BaseModel):
    grader_type: GraderType
    required: bool
    outcome: GraderOutcome
    passed: bool | None
    score: float | None = Field(default=None, ge=0, le=1)
    message: str = Field(max_length=2_000)
    expected: JsonValue
    actual: JsonValue
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=50)


class GraderResultView(GraderResultDraft):
    id: UUID


class EvaluationCaseResultView(BaseModel):
    id: UUID
    evaluation_run_id: UUID
    case_id: UUID
    run_id: UUID | None = None
    status: EvaluationCaseStatus | None = None
    case_snapshot: dict[str, Any]
    actual_output: str | None = None
    run_status: RunStatus | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    graders_passed: int = Field(ge=0)
    graders_total: int = Field(ge=0)
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    grader_results: list[GraderResultView] = Field(default_factory=list)


class EvaluationExecutionRecord(BaseModel):
    run: EvaluationRunView
    suite_snapshot: dict[str, Any]
    agent_snapshot: dict[str, Any]
    active_run_id: UUID | None = None


class EvaluationAggregate(BaseModel):
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    error_cases: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    average_duration_ms: float | None = Field(default=None, ge=0)
    p95_duration_ms: float | None = Field(default=None, ge=0)
    grader_metrics: dict[str, GraderMetric] = Field(default_factory=dict)
