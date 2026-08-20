from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.service import AgentService
from app.domain.contracts import (
    AgentDefinition,
    RunKind,
    RunRequest,
    RunStatus,
    RuntimeLimits,
)
from app.domain.errors import EntityNotFoundError
from app.evaluation.aggregation import aggregate_evaluation
from app.evaluation.contracts import (
    EvaluationCaseCreate,
    EvaluationCaseResultView,
    EvaluationCaseSetup,
    EvaluationCaseStatus,
    EvaluationCaseUpdate,
    EvaluationCaseView,
    EvaluationRunStatus,
    EvaluationRunView,
    EvaluationSuiteCreate,
    EvaluationSuiteSummary,
    EvaluationSuiteUpdate,
    EvaluationSuiteView,
)
from app.evaluation.graders import DeterministicGrader, EvaluationContext, case_status
from app.evaluation.repository import EvaluationRepository
from app.memory.contracts import MemoryKind, MemoryRecord, MemoryStore
from app.observability.redaction import redact_text, redact_value
from app.persistence.repositories import Repositories

logger = logging.getLogger(__name__)
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class EvaluationService:
    def __init__(
        self,
        repository: EvaluationRepository,
        repositories: Repositories,
        agent_service: AgentService,
        memory_store: MemoryStore,
        grader: DeterministicGrader | None = None,
    ) -> None:
        self._repository = repository
        self._repositories = repositories
        self._agent_service = agent_service
        self._memory_store = memory_store
        self._grader = grader or DeterministicGrader()
        self._enqueue: Callable[[UUID], None] | None = None
        self._start_lock = asyncio.Lock()

    def bind_enqueue(self, enqueue: Callable[[UUID], None]) -> None:
        self._enqueue = enqueue

    async def create_suite(self, data: EvaluationSuiteCreate) -> EvaluationSuiteView:
        await self._agent_service.get_agent(data.agent_id)
        _reject_sensitive_definition(data.model_dump(mode="json"), "Evaluation suite")
        return await self._repository.create_suite(data)

    async def list_suites(self) -> list[EvaluationSuiteSummary]:
        return await self._repository.list_suites()

    async def get_suite(self, suite_id: UUID) -> EvaluationSuiteView:
        return await self._repository.get_suite(suite_id)

    async def update_suite(
        self, suite_id: UUID, data: EvaluationSuiteUpdate
    ) -> EvaluationSuiteView:
        if data.agent_id is not None:
            await self._agent_service.get_agent(data.agent_id)
        _reject_sensitive_definition(
            data.model_dump(mode="json", exclude_unset=True), "Evaluation suite update"
        )
        return await self._repository.update_suite(suite_id, data)

    async def delete_suite(self, suite_id: UUID) -> None:
        await self._repository.delete_suite(suite_id)

    async def create_case(
        self, suite_id: UUID, data: EvaluationCaseCreate
    ) -> EvaluationCaseView:
        _reject_sensitive_definition(data.model_dump(mode="json"), "Evaluation case")
        return await self._repository.create_case(suite_id, data)

    async def update_case(
        self, case_id: UUID, data: EvaluationCaseUpdate
    ) -> EvaluationCaseView:
        _reject_sensitive_definition(
            data.model_dump(mode="json", exclude_unset=True), "Evaluation case update"
        )
        return await self._repository.update_case(case_id, data)

    async def delete_case(self, case_id: UUID) -> None:
        await self._repository.delete_case(case_id)

    async def start_run(
        self, suite_id: UUID, request_key: str | None = None
    ) -> EvaluationRunView:
        if request_key is not None and not _REQUEST_KEY.fullmatch(request_key):
            raise ValueError(
                "Idempotency-Key must use 1-120 letters, numbers, dots, underscores, "
                "colons, or hyphens."
            )
        suite = await self._repository.get_suite(suite_id)
        agent = await self._agent_service.get_agent(suite.agent_id)
        enabled_cases = [case for case in suite.cases if case.enabled]
        case_snapshots: list[dict[str, object]] = []
        for case in enabled_cases:
            snapshot = case.model_dump(mode="json")
            snapshot["definition_hash"] = _stable_hash(snapshot)
            case_snapshots.append(snapshot)
        suite_snapshot: dict[str, object] = {
            "id": str(suite.id),
            "name": suite.name,
            "description": suite.description,
            "agent_id": str(suite.agent_id),
            "revision": suite.revision,
            "cases": case_snapshots,
        }
        suite_snapshot["definition_hash"] = _stable_hash(suite_snapshot)
        agent_data = agent.model_dump(mode="json")
        _reject_sensitive_definition(agent_data, "Agent configuration")
        limits = RuntimeLimits().model_dump(mode="json")
        agent_snapshot: dict[str, object] = {
            "agent": agent_data,
            "runtime_limits": limits,
        }
        agent_snapshot["config_hash"] = _stable_hash(agent_snapshot)
        # v1 uses a single local process, so serialize the short check-and-create
        # boundary to make request-key and active-Suite deduplication race-safe.
        async with self._start_lock:
            evaluation_run, created = await self._repository.create_run(
                suite, suite_snapshot, agent_snapshot, request_key
            )
        if created:
            if self._enqueue is None:
                raise RuntimeError("Evaluation worker is not configured.")
            self._enqueue(evaluation_run.id)
        return evaluation_run

    async def get_run(self, evaluation_run_id: UUID) -> EvaluationRunView:
        return await self._repository.get_run(evaluation_run_id)

    async def list_results(
        self, evaluation_run_id: UUID
    ) -> list[EvaluationCaseResultView]:
        return await self._repository.list_results(evaluation_run_id)

    async def cancel_run(self, evaluation_run_id: UUID) -> EvaluationRunView:
        record = await self._repository.request_cancel(evaluation_run_id)
        if record.active_run_id is not None:
            try:
                await self._agent_service.cancel_run(record.active_run_id)
            except EntityNotFoundError:
                logger.warning(
                    "Active evaluation agent run %s was missing during cancellation.",
                    record.active_run_id,
                )
        return await self._repository.get_run(evaluation_run_id)

    async def process_run(self, evaluation_run_id: UUID) -> None:
        record = await self._repository.get_execution(evaluation_run_id)
        if record.run.status in {
            EvaluationRunStatus.COMPLETED,
            EvaluationRunStatus.FAILED,
            EvaluationRunStatus.CANCELLED,
        }:
            return
        if record.run.cancel_requested:
            await self._repository.finish_run(
                evaluation_run_id, EvaluationRunStatus.CANCELLED
            )
            return
        await self._repository.mark_running(evaluation_run_id)
        try:
            await self._execute_cases(evaluation_run_id, record)
        except Exception:
            logger.exception(
                "Evaluation run escaped its infrastructure boundary.",
                extra={"evaluation_run_id": str(evaluation_run_id)},
            )
            await self._refresh_aggregate(evaluation_run_id, record.run.total_cases)
            await self._repository.finish_run(
                evaluation_run_id,
                EvaluationRunStatus.FAILED,
                error="Evaluation infrastructure failed unexpectedly.",
            )

    async def _execute_cases(self, evaluation_run_id: UUID, record: object) -> None:
        execution = await self._repository.get_execution(evaluation_run_id)
        raw_agent = execution.agent_snapshot.get("agent")
        if not isinstance(raw_agent, dict):
            raise ValueError("Evaluation agent snapshot is invalid.")
        source_agent = AgentDefinition.model_validate(raw_agent)
        raw_cases = execution.suite_snapshot.get("cases")
        if not isinstance(raw_cases, list):
            raise ValueError("Evaluation suite snapshot is invalid.")
        existing = await self._repository.existing_case_ids(evaluation_run_id)
        for raw_case in raw_cases:
            latest = await self._repository.get_run(evaluation_run_id)
            if latest.cancel_requested:
                await self._repository.finish_run(
                    evaluation_run_id, EvaluationRunStatus.CANCELLED
                )
                return
            if not isinstance(raw_case, dict):
                raise ValueError("Evaluation case snapshot is invalid.")
            case = EvaluationCaseView.model_validate(raw_case)
            if case.id in existing:
                continue
            case_result_id = await self._repository.begin_case(
                evaluation_run_id, case.id, raw_case
            )
            try:
                await self._execute_case(
                    evaluation_run_id,
                    case_result_id,
                    case,
                    source_agent,
                )
            except Exception as exc:
                logger.exception(
                    "Evaluation case infrastructure failed.",
                    extra={
                        "evaluation_run_id": str(evaluation_run_id),
                        "case_id": str(case.id),
                    },
                )
                await self._repository.finish_case(
                    case_result_id,
                    EvaluationCaseStatus.ERROR,
                    None,
                    [],
                    error=redact_text(
                        f"Evaluation case could not execute ({type(exc).__name__})."
                    ),
                )
            await self._refresh_aggregate(evaluation_run_id, len(raw_cases))
        latest = await self._repository.get_run(evaluation_run_id)
        await self._repository.finish_run(
            evaluation_run_id,
            EvaluationRunStatus.CANCELLED
            if latest.cancel_requested
            else EvaluationRunStatus.COMPLETED,
        )

    async def _execute_case(
        self,
        evaluation_run_id: UUID,
        case_result_id: UUID,
        case: EvaluationCaseView,
        source_agent: AgentDefinition,
    ) -> None:
        evaluation_agent = await self._repositories.create_evaluation_agent(source_agent)
        await self._seed_memory(
            evaluation_run_id, case.id, evaluation_agent.id, case.setup
        )
        run = await self._agent_service.create_run(
            evaluation_agent.id,
            RunRequest(input=case.input),
            run_kind=RunKind.EVALUATION,
        )
        await self._repository.attach_case_execution(
            evaluation_run_id,
            case_result_id,
            evaluation_agent.id,
            run.id,
        )
        terminal = await self._agent_service.wait_for_terminal(run.id)
        latest = await self._repository.get_run(evaluation_run_id)
        if latest.cancel_requested:
            observability = await self._agent_service.get_run_observability(run.id)
            await self._repository.finish_case(
                case_result_id,
                EvaluationCaseStatus.ERROR,
                observability.duration_ms,
                [],
                error="Evaluation was cancelled while this case was executing.",
            )
            return
        events = await self._agent_service.list_events(run.id)
        observability = await self._agent_service.get_run_observability(run.id)
        context = EvaluationContext(
            run=terminal,
            events=events,
            observability=observability,
        )
        grader_results = [
            self._grader.grade(config, context) for config in case.graders
        ]
        await self._repository.finish_case(
            case_result_id,
            case_status(grader_results),
            observability.duration_ms,
            grader_results,
        )

    async def _seed_memory(
        self,
        evaluation_run_id: UUID,
        case_id: UUID,
        evaluation_agent_id: UUID,
        setup: EvaluationCaseSetup,
    ) -> None:
        timestamp = datetime.now(UTC)
        for seed in setup.memories:
            await self._memory_store.write(
                MemoryRecord(
                    agent_id=evaluation_agent_id,
                    kind=MemoryKind.LONG_TERM,
                    content=seed.content,
                    importance=seed.importance,
                    created_at=timestamp,
                    expires_at=timestamp + timedelta(days=180),
                    metadata={
                        "source": "evaluation_setup",
                        "evaluation_run_id": str(evaluation_run_id),
                        "evaluation_case_id": str(case_id),
                    },
                )
            )

    async def _refresh_aggregate(
        self, evaluation_run_id: UUID, total_cases: int
    ) -> None:
        results = await self._repository.list_results(evaluation_run_id)
        await self._repository.update_aggregate(
            evaluation_run_id, aggregate_evaluation(total_cases, results)
        )

    async def recover_runs(self) -> list[UUID]:
        unfinished = await self._repository.unfinished_results()
        for result in unfinished:
            if result.run_id is not None and result.run_status in {
                RunStatus.PENDING,
                RunStatus.RUNNING,
            }:
                await self._agent_service.fail_interrupted_run(result.run_id)
            await self._repository.mark_interrupted_result(result.id)
        candidates = await self._repository.recover_candidates()
        for run_id in candidates:
            run = await self._repository.get_run(run_id)
            await self._refresh_aggregate(run_id, run.total_cases)
        return candidates


def _stable_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _reject_sensitive_definition(value: object, label: str) -> None:
    if redact_value(value) != value:
        raise ValueError(
            f"{label} contains a labelled secret. Remove secret values before evaluation."
        )
