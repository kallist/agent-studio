from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import RunStatus
from app.domain.errors import EntityNotFoundError
from app.evaluation.contracts import (
    EvaluationAggregate,
    EvaluationCaseCreate,
    EvaluationCaseResultView,
    EvaluationCaseStatus,
    EvaluationCaseUpdate,
    EvaluationCaseView,
    EvaluationExecutionRecord,
    EvaluationRunStatus,
    EvaluationRunView,
    EvaluationSuiteCreate,
    EvaluationSuiteSummary,
    EvaluationSuiteUpdate,
    EvaluationSuiteView,
    GraderMetric,
    GraderOutcome,
    GraderResultDraft,
    GraderResultView,
)
from app.observability.redaction import redact_text, redact_value
from app.persistence.models import (
    EvaluationCaseModel,
    EvaluationCaseResultModel,
    EvaluationRunModel,
    EvaluationSuiteModel,
    GraderResultModel,
    RunModel,
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EvaluationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_suite(self, data: EvaluationSuiteCreate) -> EvaluationSuiteView:
        async with self._sessions() as session:
            now = datetime.now(UTC)
            suite = EvaluationSuiteModel(
                agent_id=str(data.agent_id),
                name=redact_text(data.name.strip()),
                description=redact_text(data.description.strip()),
                revision=1,
                created_at=now,
                updated_at=now,
            )
            session.add(suite)
            await session.flush()
            for position, case in enumerate(data.cases):
                session.add(self._case_model(suite.id, case, position, now))
            await session.commit()
            suite_id = UUID(suite.id)
        return await self.get_suite(suite_id)

    async def list_suites(self) -> list[EvaluationSuiteSummary]:
        async with self._sessions() as session:
            suites = list(
                await session.scalars(
                    select(EvaluationSuiteModel)
                    .where(EvaluationSuiteModel.deleted_at.is_(None))
                    .order_by(EvaluationSuiteModel.updated_at.desc())
                )
            )
            count_rows = await session.execute(
                select(EvaluationCaseModel.suite_id, func.count(EvaluationCaseModel.id))
                .where(EvaluationCaseModel.deleted_at.is_(None))
                .group_by(EvaluationCaseModel.suite_id)
            )
            counts = {suite_id: count for suite_id, count in count_rows.all()}
            runs = list(
                await session.scalars(
                    select(EvaluationRunModel).order_by(EvaluationRunModel.created_at.desc())
                )
            )
            latest: dict[str, EvaluationRunModel] = {}
            for run in runs:
                latest.setdefault(run.suite_id, run)
            return [
                self._suite_summary(
                    suite,
                    counts.get(suite.id, 0),
                    latest.get(suite.id),
                )
                for suite in suites
            ]

    async def get_suite(self, suite_id: UUID) -> EvaluationSuiteView:
        async with self._sessions() as session:
            suite = await session.get(EvaluationSuiteModel, str(suite_id))
            if suite is None or suite.deleted_at is not None:
                raise EntityNotFoundError(f"Evaluation suite '{suite_id}' was not found.")
            cases = list(
                await session.scalars(
                    select(EvaluationCaseModel)
                    .where(
                        EvaluationCaseModel.suite_id == str(suite_id),
                        EvaluationCaseModel.deleted_at.is_(None),
                    )
                    .order_by(EvaluationCaseModel.position, EvaluationCaseModel.created_at)
                )
            )
            last_run = await session.scalar(
                select(EvaluationRunModel)
                .where(EvaluationRunModel.suite_id == str(suite_id))
                .order_by(EvaluationRunModel.created_at.desc())
                .limit(1)
            )
            summary = self._suite_summary(suite, len(cases), last_run)
            return EvaluationSuiteView(
                **summary.model_dump(),
                cases=[self._case_view(case) for case in cases],
            )

    async def update_suite(
        self, suite_id: UUID, data: EvaluationSuiteUpdate
    ) -> EvaluationSuiteView:
        async with self._sessions() as session:
            suite = await self._active_suite(session, suite_id)
            if data.name is not None:
                suite.name = redact_text(data.name.strip())
            if data.description is not None:
                suite.description = redact_text(data.description.strip())
            if data.agent_id is not None:
                suite.agent_id = str(data.agent_id)
            suite.revision += 1
            suite.updated_at = datetime.now(UTC)
            await session.commit()
        return await self.get_suite(suite_id)

    async def delete_suite(self, suite_id: UUID) -> None:
        async with self._sessions() as session:
            suite = await self._active_suite(session, suite_id)
            now = datetime.now(UTC)
            suite.deleted_at = now
            suite.updated_at = now
            suite.revision += 1
            cases = await session.scalars(
                select(EvaluationCaseModel).where(
                    EvaluationCaseModel.suite_id == str(suite_id),
                    EvaluationCaseModel.deleted_at.is_(None),
                )
            )
            for case in cases:
                case.deleted_at = now
                case.updated_at = now
            await session.commit()

    async def create_case(
        self, suite_id: UUID, data: EvaluationCaseCreate
    ) -> EvaluationCaseView:
        async with self._sessions() as session:
            suite = await self._active_suite(session, suite_id)
            position = await session.scalar(
                select(func.max(EvaluationCaseModel.position)).where(
                    EvaluationCaseModel.suite_id == str(suite_id),
                    EvaluationCaseModel.deleted_at.is_(None),
                )
            )
            now = datetime.now(UTC)
            next_position = int(position) + 1 if position is not None else 0
            case = self._case_model(suite.id, data, next_position, now)
            session.add(case)
            suite.revision += 1
            suite.updated_at = now
            await session.commit()
            await session.refresh(case)
            return self._case_view(case)

    async def update_case(
        self, case_id: UUID, data: EvaluationCaseUpdate
    ) -> EvaluationCaseView:
        async with self._sessions() as session:
            case = await self._active_case(session, case_id)
            suite = await self._active_suite(session, UUID(case.suite_id))
            if data.name is not None:
                case.name = redact_text(data.name.strip())
            if data.input is not None:
                case.input = redact_text(data.input.strip())
            if data.enabled is not None:
                case.enabled = data.enabled
            if data.graders is not None:
                case.graders_json = _json(
                    redact_value(
                        [grader.model_dump(mode="json") for grader in data.graders]
                    )
                )
            if data.setup is not None:
                case.setup_json = _json(
                    redact_value(data.setup.model_dump(mode="json"))
                )
            now = datetime.now(UTC)
            case.updated_at = now
            suite.revision += 1
            suite.updated_at = now
            await session.commit()
            await session.refresh(case)
            return self._case_view(case)

    async def delete_case(self, case_id: UUID) -> None:
        async with self._sessions() as session:
            case = await self._active_case(session, case_id)
            suite = await self._active_suite(session, UUID(case.suite_id))
            now = datetime.now(UTC)
            case.deleted_at = now
            case.updated_at = now
            suite.revision += 1
            suite.updated_at = now
            await session.commit()

    async def create_run(
        self,
        suite: EvaluationSuiteView,
        suite_snapshot: dict[str, object],
        agent_snapshot: dict[str, object],
        request_key: str | None,
    ) -> tuple[EvaluationRunView, bool]:
        async with self._sessions() as session:
            if request_key is not None:
                existing = await session.scalar(
                    select(EvaluationRunModel).where(
                        EvaluationRunModel.request_key == request_key
                    )
                )
                if existing is not None:
                    return self._run_view(existing), False
            active = await session.scalar(
                select(EvaluationRunModel)
                .where(
                    EvaluationRunModel.suite_id == str(suite.id),
                    EvaluationRunModel.status.in_(
                        [EvaluationRunStatus.QUEUED.value, EvaluationRunStatus.RUNNING.value]
                    ),
                )
                .order_by(EvaluationRunModel.created_at.desc())
                .limit(1)
            )
            if active is not None:
                return self._run_view(active), False
            enabled_cases = [case for case in suite.cases if case.enabled]
            model = EvaluationRunModel(
                suite_id=str(suite.id),
                agent_id=str(suite.agent_id),
                status=EvaluationRunStatus.QUEUED.value,
                suite_revision=suite.revision,
                suite_snapshot_json=_json(suite_snapshot),
                agent_snapshot_json=_json(agent_snapshot),
                request_key=request_key,
                total_cases=len(enabled_cases),
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return self._run_view(model), True

    async def get_run(self, evaluation_run_id: UUID) -> EvaluationRunView:
        async with self._sessions() as session:
            model = await session.get(EvaluationRunModel, str(evaluation_run_id))
            if model is None:
                raise EntityNotFoundError(
                    f"Evaluation run '{evaluation_run_id}' was not found."
                )
            return self._run_view(model)

    async def get_execution(self, evaluation_run_id: UUID) -> EvaluationExecutionRecord:
        async with self._sessions() as session:
            model = await session.get(EvaluationRunModel, str(evaluation_run_id))
            if model is None:
                raise EntityNotFoundError(
                    f"Evaluation run '{evaluation_run_id}' was not found."
                )
            return EvaluationExecutionRecord(
                run=self._run_view(model),
                suite_snapshot=json.loads(model.suite_snapshot_json),
                agent_snapshot=json.loads(model.agent_snapshot_json),
                active_run_id=UUID(model.active_run_id) if model.active_run_id else None,
            )

    async def mark_running(self, evaluation_run_id: UUID) -> None:
        async with self._sessions() as session:
            model = await self._evaluation_run(session, evaluation_run_id)
            if model.status == EvaluationRunStatus.CANCELLED.value:
                return
            model.status = EvaluationRunStatus.RUNNING.value
            model.started_at = model.started_at or datetime.now(UTC)
            model.error = None
            await session.commit()

    async def begin_case(
        self, evaluation_run_id: UUID, case_id: UUID, case_snapshot: dict[str, object]
    ) -> UUID:
        async with self._sessions() as session:
            model = EvaluationCaseResultModel(
                evaluation_run_id=str(evaluation_run_id),
                case_id=str(case_id),
                case_snapshot_json=_json(case_snapshot),
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return UUID(model.id)

    async def attach_case_execution(
        self,
        evaluation_run_id: UUID,
        case_result_id: UUID,
        evaluation_agent_id: UUID,
        run_id: UUID,
    ) -> None:
        async with self._sessions() as session:
            evaluation_run = await self._evaluation_run(session, evaluation_run_id)
            result = await self._case_result(session, case_result_id)
            result.evaluation_agent_id = str(evaluation_agent_id)
            result.run_id = str(run_id)
            evaluation_run.active_run_id = str(run_id)
            await session.commit()

    async def finish_case(
        self,
        case_result_id: UUID,
        status: EvaluationCaseStatus,
        duration_ms: float | None,
        graders: list[GraderResultDraft],
        *,
        error: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            result = await self._case_result(session, case_result_id)
            result.status = status.value
            result.duration_ms = duration_ms
            result.graders_total = len(graders)
            result.graders_passed = sum(
                grader.outcome == GraderOutcome.PASS for grader in graders
            )
            result.error = redact_text(error) if error is not None else None
            result.completed_at = datetime.now(UTC)
            for grader in graders:
                expected = redact_value(grader.expected)
                actual = redact_value(grader.actual)
                evidence = redact_value(grader.evidence)
                session.add(
                    GraderResultModel(
                        case_result_id=result.id,
                        grader_type=grader.grader_type.value,
                        required=grader.required,
                        outcome=grader.outcome.value,
                        passed=grader.passed,
                        score=grader.score,
                        message=redact_text(grader.message),
                        expected_json=_json(expected),
                        actual_json=_json(actual),
                        evidence_json=_json(evidence),
                    )
                )
            evaluation_run = await self._evaluation_run(
                session, UUID(result.evaluation_run_id)
            )
            evaluation_run.active_run_id = None
            await session.commit()

    async def list_results(
        self, evaluation_run_id: UUID
    ) -> list[EvaluationCaseResultView]:
        async with self._sessions() as session:
            await self._evaluation_run(session, evaluation_run_id)
            results = list(
                await session.scalars(
                    select(EvaluationCaseResultModel)
                    .where(
                        EvaluationCaseResultModel.evaluation_run_id
                        == str(evaluation_run_id)
                    )
                    .order_by(EvaluationCaseResultModel.created_at)
                )
            )
            result_ids = [result.id for result in results]
            graders = list(
                await session.scalars(
                    select(GraderResultModel)
                    .where(GraderResultModel.case_result_id.in_(result_ids))
                    .order_by(GraderResultModel.id)
                )
            ) if result_ids else []
            graders_by_result: dict[str, list[GraderResultModel]] = {
                result_id: [] for result_id in result_ids
            }
            for grader in graders:
                graders_by_result[grader.case_result_id].append(grader)
            run_ids = [result.run_id for result in results if result.run_id]
            runs = list(
                await session.scalars(select(RunModel).where(RunModel.id.in_(run_ids)))
            ) if run_ids else []
            runs_by_id = {run.id: run for run in runs}
            return [
                self._case_result_view(
                    result,
                    graders_by_result.get(result.id, []),
                    runs_by_id.get(result.run_id or ""),
                )
                for result in results
            ]

    async def update_aggregate(
        self, evaluation_run_id: UUID, aggregate: EvaluationAggregate
    ) -> None:
        async with self._sessions() as session:
            model = await self._evaluation_run(session, evaluation_run_id)
            model.total_cases = aggregate.total_cases
            model.completed_cases = aggregate.completed_cases
            model.passed_cases = aggregate.passed_cases
            model.failed_cases = aggregate.failed_cases
            model.error_cases = aggregate.error_cases
            model.pass_rate = aggregate.pass_rate
            model.average_duration_ms = aggregate.average_duration_ms
            model.p95_duration_ms = aggregate.p95_duration_ms
            model.grader_metrics_json = _json(
                {
                    name: metric.model_dump(mode="json")
                    for name, metric in aggregate.grader_metrics.items()
                }
            )
            await session.commit()

    async def finish_run(
        self,
        evaluation_run_id: UUID,
        status: EvaluationRunStatus,
        *,
        error: str | None = None,
    ) -> None:
        async with self._sessions() as session:
            model = await self._evaluation_run(session, evaluation_run_id)
            model.status = status.value
            model.error = redact_text(error) if error is not None else None
            model.active_run_id = None
            model.completed_at = datetime.now(UTC)
            await session.commit()

    async def request_cancel(self, evaluation_run_id: UUID) -> EvaluationExecutionRecord:
        async with self._sessions() as session:
            model = await self._evaluation_run(session, evaluation_run_id)
            if model.status not in {
                EvaluationRunStatus.COMPLETED.value,
                EvaluationRunStatus.FAILED.value,
                EvaluationRunStatus.CANCELLED.value,
            }:
                model.cancel_requested = True
                await session.commit()
            return EvaluationExecutionRecord(
                run=self._run_view(model),
                suite_snapshot=json.loads(model.suite_snapshot_json),
                agent_snapshot=json.loads(model.agent_snapshot_json),
                active_run_id=UUID(model.active_run_id) if model.active_run_id else None,
            )

    async def existing_case_ids(self, evaluation_run_id: UUID) -> set[UUID]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(EvaluationCaseResultModel.case_id).where(
                    EvaluationCaseResultModel.evaluation_run_id == str(evaluation_run_id)
                )
            )
            return {UUID(value) for value in rows}

    async def recover_candidates(self) -> list[UUID]:
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(EvaluationRunModel).where(
                        EvaluationRunModel.status.in_(
                            [
                                EvaluationRunStatus.QUEUED.value,
                                EvaluationRunStatus.RUNNING.value,
                            ]
                        )
                    )
                )
            )
            for row in rows:
                row.status = EvaluationRunStatus.QUEUED.value
                row.active_run_id = None
            await session.commit()
            return [UUID(row.id) for row in rows]

    async def unfinished_results(self) -> list[EvaluationCaseResultView]:
        async with self._sessions() as session:
            results = list(
                await session.scalars(
                    select(EvaluationCaseResultModel).where(
                        EvaluationCaseResultModel.status.is_(None)
                    )
                )
            )
            run_ids = [result.run_id for result in results if result.run_id]
            runs = list(
                await session.scalars(select(RunModel).where(RunModel.id.in_(run_ids)))
            ) if run_ids else []
            runs_by_id = {run.id: run for run in runs}
            return [
                self._case_result_view(result, [], runs_by_id.get(result.run_id or ""))
                for result in results
            ]

    async def mark_interrupted_result(self, case_result_id: UUID) -> None:
        await self.finish_case(
            case_result_id,
            EvaluationCaseStatus.ERROR,
            None,
            [],
            error="Evaluation worker restarted while this case was executing.",
        )

    async def _active_suite(
        self, session: AsyncSession, suite_id: UUID
    ) -> EvaluationSuiteModel:
        suite = await session.get(EvaluationSuiteModel, str(suite_id))
        if suite is None or suite.deleted_at is not None:
            raise EntityNotFoundError(f"Evaluation suite '{suite_id}' was not found.")
        return suite

    async def _active_case(
        self, session: AsyncSession, case_id: UUID
    ) -> EvaluationCaseModel:
        case = await session.get(EvaluationCaseModel, str(case_id))
        if case is None or case.deleted_at is not None:
            raise EntityNotFoundError(f"Evaluation case '{case_id}' was not found.")
        return case

    async def _evaluation_run(
        self, session: AsyncSession, evaluation_run_id: UUID
    ) -> EvaluationRunModel:
        model = await session.get(EvaluationRunModel, str(evaluation_run_id))
        if model is None:
            raise EntityNotFoundError(
                f"Evaluation run '{evaluation_run_id}' was not found."
            )
        return model

    async def _case_result(
        self, session: AsyncSession, case_result_id: UUID
    ) -> EvaluationCaseResultModel:
        model = await session.get(EvaluationCaseResultModel, str(case_result_id))
        if model is None:
            raise EntityNotFoundError(
                f"Evaluation case result '{case_result_id}' was not found."
            )
        return model

    @staticmethod
    def _case_model(
        suite_id: str,
        data: EvaluationCaseCreate,
        position: int,
        timestamp: datetime,
    ) -> EvaluationCaseModel:
        return EvaluationCaseModel(
            suite_id=suite_id,
            name=redact_text(data.name.strip()),
            input=redact_text(data.input.strip()),
            enabled=data.enabled,
            graders_json=_json(
                redact_value(
                    [grader.model_dump(mode="json") for grader in data.graders]
                )
            ),
            setup_json=_json(redact_value(data.setup.model_dump(mode="json"))),
            position=position,
            created_at=timestamp,
            updated_at=timestamp,
        )

    @staticmethod
    def _case_view(model: EvaluationCaseModel) -> EvaluationCaseView:
        return EvaluationCaseView(
            id=UUID(model.id),
            suite_id=UUID(model.suite_id),
            name=model.name,
            input=model.input,
            enabled=model.enabled,
            graders=json.loads(model.graders_json),
            setup=json.loads(model.setup_json),
            position=model.position,
            created_at=_aware(model.created_at),
            updated_at=_aware(model.updated_at),
        )

    @staticmethod
    def _suite_summary(
        model: EvaluationSuiteModel,
        case_count: int,
        last_run: EvaluationRunModel | None,
    ) -> EvaluationSuiteSummary:
        return EvaluationSuiteSummary(
            id=UUID(model.id),
            name=model.name,
            description=model.description,
            agent_id=UUID(model.agent_id),
            revision=model.revision,
            case_count=case_count,
            last_run_id=UUID(last_run.id) if last_run else None,
            last_run_status=(EvaluationRunStatus(last_run.status) if last_run else None),
            last_pass_rate=last_run.pass_rate if last_run else None,
            created_at=_aware(model.created_at),
            updated_at=_aware(model.updated_at),
        )

    @staticmethod
    def _run_view(model: EvaluationRunModel) -> EvaluationRunView:
        raw_metrics = json.loads(model.grader_metrics_json or "{}")
        return EvaluationRunView(
            id=UUID(model.id),
            suite_id=UUID(model.suite_id),
            agent_id=UUID(model.agent_id),
            status=EvaluationRunStatus(model.status),
            suite_revision=model.suite_revision,
            total_cases=model.total_cases,
            completed_cases=model.completed_cases,
            passed_cases=model.passed_cases,
            failed_cases=model.failed_cases,
            error_cases=model.error_cases,
            pass_rate=model.pass_rate,
            average_duration_ms=model.average_duration_ms,
            p95_duration_ms=model.p95_duration_ms,
            grader_metrics={
                name: GraderMetric.model_validate(metric)
                for name, metric in raw_metrics.items()
            },
            cancel_requested=model.cancel_requested,
            error=model.error,
            created_at=_aware(model.created_at),
            started_at=_aware(model.started_at) if model.started_at else None,
            completed_at=_aware(model.completed_at) if model.completed_at else None,
        )

    @staticmethod
    def _case_result_view(
        model: EvaluationCaseResultModel,
        graders: list[GraderResultModel],
        run: RunModel | None,
    ) -> EvaluationCaseResultView:
        return EvaluationCaseResultView(
            id=UUID(model.id),
            evaluation_run_id=UUID(model.evaluation_run_id),
            case_id=UUID(model.case_id),
            run_id=UUID(model.run_id) if model.run_id else None,
            status=EvaluationCaseStatus(model.status) if model.status else None,
            case_snapshot=json.loads(model.case_snapshot_json),
            actual_output=(
                redact_text(run.output)
                if run is not None and run.output is not None
                else None
            ),
            run_status=RunStatus(run.status) if run else None,
            duration_ms=model.duration_ms,
            graders_passed=model.graders_passed,
            graders_total=model.graders_total,
            error=model.error,
            created_at=_aware(model.created_at),
            completed_at=_aware(model.completed_at) if model.completed_at else None,
            grader_results=[
                GraderResultView(
                    id=UUID(grader.id),
                    grader_type=grader.grader_type,
                    required=grader.required,
                    outcome=GraderOutcome(grader.outcome),
                    passed=grader.passed,
                    score=grader.score,
                    message=grader.message,
                    expected=json.loads(grader.expected_json),
                    actual=json.loads(grader.actual_json),
                    evidence=json.loads(grader.evidence_json),
                )
                for grader in graders
            ],
        )
