from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain.contracts import (
    AgentEvent,
    RunObservability,
    RunResult,
    RunStatus,
    ToolCallCounts,
)
from app.evaluation.aggregation import aggregate_evaluation
from app.evaluation.contracts import (
    EvaluationCaseResultView,
    EvaluationCaseStatus,
    GraderConfig,
    GraderOutcome,
    GraderResultView,
    GraderType,
)
from app.evaluation.graders import DeterministicGrader, EvaluationContext, case_status

NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _context(
    *,
    output: str | None = "5192",
    status: RunStatus = RunStatus.COMPLETED,
    events: list[AgentEvent] | None = None,
    steps: int = 2,
    duration_ms: float | None = 125,
) -> EvaluationContext:
    run_id = UUID(int=10)
    run = RunResult(
        id=run_id,
        agent_id=UUID(int=11),
        status=status,
        input="Calculate 128 * 37 + 456",
        output=output,
        created_at=NOW,
        updated_at=NOW,
    )
    observability = RunObservability(
        run_id=run_id,
        agent_id=run.agent_id,
        status=status,
        created_at=NOW,
        duration_ms=duration_ms,
        event_count=len(events or []),
        step_count=steps,
        tool_calls=ToolCallCounts(total=0, succeeded=0, failed=0),
    )
    return EvaluationContext(run=run, events=events or [], observability=observability)


def _event(event_type: str, payload: dict[str, object], sequence: int = 1) -> AgentEvent:
    return AgentEvent(
        run_id=UUID(int=10),
        sequence=sequence,
        type=event_type,
        timestamp=NOW,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("config", "context", "expected"),
    [
        (GraderConfig(type="run_status"), _context(), True),
        (
            GraderConfig(type="run_status", expected_status="failed"),
            _context(),
            False,
        ),
        (GraderConfig(type="final_output_non_empty"), _context(output=" value "), True),
        (GraderConfig(type="final_output_non_empty"), _context(output="  "), False),
        (GraderConfig(type="exact_match", value="5192"), _context(output=" 5192\n"), True),
        (GraderConfig(type="exact_match", value="5193"), _context(), False),
        (
            GraderConfig(type="exact_match", value="answer", case_sensitive=False),
            _context(output="Answer"),
            True,
        ),
        (
            GraderConfig(type="exact_match", value="answer", case_sensitive=True),
            _context(output="Answer"),
            False,
        ),
        (GraderConfig(type="contains", value="19"), _context(), True),
        (GraderConfig(type="contains", value="9999"), _context(), False),
        (GraderConfig(type="max_steps", maximum=2), _context(steps=1), True),
        (GraderConfig(type="max_steps", maximum=2), _context(steps=2), True),
        (GraderConfig(type="max_steps", maximum=2), _context(steps=3), False),
        (GraderConfig(type="max_duration", maximum=125), _context(duration_ms=124), True),
        (GraderConfig(type="max_duration", maximum=125), _context(duration_ms=125), True),
        (GraderConfig(type="max_duration", maximum=125), _context(duration_ms=126), False),
    ],
)
def test_scalar_graders(
    config: GraderConfig, context: EvaluationContext, expected: bool
) -> None:
    result = DeterministicGrader().grade(config, context)
    assert result.passed is expected
    assert result.score == (1.0 if expected else 0.0)


def test_max_duration_unavailable_is_error_not_pass() -> None:
    result = DeterministicGrader().grade(
        GraderConfig(type="max_duration", maximum=100),
        _context(duration_ms=None),
    )
    assert result.outcome == GraderOutcome.ERROR
    assert result.passed is None
    assert result.score is None


def test_tool_selection_and_forbidden_tool_use_real_events() -> None:
    calculator = _event("tool.selected", {"tool": "calculator"})
    context = _context(events=[calculator])
    selected = DeterministicGrader().grade(
        GraderConfig(type="tool_selected", tool_name="calculator"), context
    )
    missing = DeterministicGrader().grade(
        GraderConfig(type="tool_selected", tool_name="knowledge_search"), context
    )
    absent = DeterministicGrader().grade(
        GraderConfig(type="tool_not_selected", tool_name="knowledge_search"), context
    )
    forbidden = DeterministicGrader().grade(
        GraderConfig(type="tool_not_selected", tool_name="calculator"), context
    )
    assert (selected.passed, missing.passed, absent.passed, forbidden.passed) == (
        True,
        False,
        True,
        False,
    )
    assert selected.evidence[0]["event_id"] == str(calculator.event_id)


def test_retrieval_and_citation_require_matching_provenance() -> None:
    event = _event(
        "tool.completed",
        {
            "tool": "knowledge_search",
            "result": {
                "results": [
                    {
                        "document_id": str(UUID(int=22)),
                        "document": "policy.md",
                        "source": "upload://policy.md",
                    }
                ]
            },
        },
    )
    context = _context(events=[event])
    grader = DeterministicGrader()
    assert grader.grade(
        GraderConfig(type="retrieval_hit", expected_source="upload://policy.md"), context
    ).passed
    assert not grader.grade(
        GraderConfig(type="retrieval_hit", expected_source="upload://wrong.md"), context
    ).passed
    assert not grader.grade(
        GraderConfig(type="retrieval_hit"), _context(events=[])
    ).passed
    assert grader.grade(
        GraderConfig(type="citation", expected_document_id=UUID(int=22)), context
    ).passed
    assert not grader.grade(
        GraderConfig(type="citation", expected_source="upload://wrong.md"), context
    ).passed
    assert not grader.grade(GraderConfig(type="citation"), _context(events=[])).passed


def test_memory_retrieval_requires_real_positive_event() -> None:
    grader = DeterministicGrader()
    assert grader.grade(
        GraderConfig(type="memory_retrieved"),
        _context(events=[_event("memory.retrieved", {"count": 1})]),
    ).passed
    assert not grader.grade(
        GraderConfig(type="memory_retrieved"),
        _context(events=[_event("memory.retrieval.skipped", {"count": 0})]),
    ).passed


def test_case_status_distinguishes_fail_from_error() -> None:
    grader = DeterministicGrader()
    passed = grader.grade(GraderConfig(type="contains", value="5192"), _context())
    failed = grader.grade(GraderConfig(type="contains", value="9999"), _context())
    error = grader.grade(
        GraderConfig(type="max_duration", maximum=1), _context(duration_ms=None)
    )
    assert case_status([passed]) == EvaluationCaseStatus.PASS
    assert case_status([passed, failed]) == EvaluationCaseStatus.FAIL
    assert case_status([passed, error]) == EvaluationCaseStatus.ERROR
    optional_error = error.model_copy(update={"required": False})
    assert case_status([passed, optional_error]) == EvaluationCaseStatus.PASS


def _result(
    status: EvaluationCaseStatus,
    duration: float | None = 100,
) -> EvaluationCaseResultView:
    outcome = {
        EvaluationCaseStatus.PASS: GraderOutcome.PASS,
        EvaluationCaseStatus.FAIL: GraderOutcome.FAIL,
        EvaluationCaseStatus.ERROR: GraderOutcome.ERROR,
    }[status]
    grader = GraderResultView(
        id=uuid4(),
        grader_type=GraderType.RUN_STATUS,
        required=True,
        outcome=outcome,
        passed=(
            True
            if outcome == GraderOutcome.PASS
            else False if outcome == GraderOutcome.FAIL else None
        ),
        score=(
            1.0
            if outcome == GraderOutcome.PASS
            else 0.0 if outcome == GraderOutcome.FAIL else None
        ),
        message="fixture",
        expected="completed",
        actual="completed",
    )
    return EvaluationCaseResultView(
        id=uuid4(),
        evaluation_run_id=uuid4(),
        case_id=uuid4(),
        status=status,
        case_snapshot={"name": "fixture"},
        duration_ms=duration,
        graders_passed=1 if status == EvaluationCaseStatus.PASS else 0,
        graders_total=1,
        created_at=NOW,
        completed_at=NOW,
        grader_results=[grader],
    )


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], (0, 0, 0, 0, None)),
        ([_result(EvaluationCaseStatus.PASS)], (1, 1, 0, 0, 1.0)),
        ([_result(EvaluationCaseStatus.FAIL)], (1, 0, 1, 0, 0.0)),
        (
            [
                _result(EvaluationCaseStatus.PASS),
                _result(EvaluationCaseStatus.PASS),
                _result(EvaluationCaseStatus.PASS),
                _result(EvaluationCaseStatus.FAIL),
                _result(EvaluationCaseStatus.ERROR),
            ],
            (5, 3, 1, 1, 0.6),
        ),
    ],
)
def test_aggregate_math(
    results: list[EvaluationCaseResultView],
    expected: tuple[int, int, int, int, float | None],
) -> None:
    aggregate = aggregate_evaluation(len(results), results)
    assert (
        aggregate.completed_cases,
        aggregate.passed_cases,
        aggregate.failed_cases,
        aggregate.error_cases,
        aggregate.pass_rate,
    ) == expected


def test_p95_uses_nearest_rank_and_ignores_unavailable_durations() -> None:
    results = [
        _result(EvaluationCaseStatus.PASS, duration)
        for duration in [10, 20, 30, 40, 50, None]
    ]
    aggregate = aggregate_evaluation(6, results)
    assert aggregate.average_duration_ms == 30
    assert aggregate.p95_duration_ms == 50
