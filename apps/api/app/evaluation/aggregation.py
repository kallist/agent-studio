from __future__ import annotations

from collections import defaultdict
from math import ceil

from app.evaluation.contracts import (
    EvaluationAggregate,
    EvaluationCaseResultView,
    EvaluationCaseStatus,
    GraderMetric,
    GraderOutcome,
)


def aggregate_evaluation(
    total_cases: int,
    results: list[EvaluationCaseResultView],
) -> EvaluationAggregate:
    completed = [result for result in results if result.status is not None]
    passed = sum(result.status == EvaluationCaseStatus.PASS for result in completed)
    failed = sum(result.status == EvaluationCaseStatus.FAIL for result in completed)
    errors = sum(result.status == EvaluationCaseStatus.ERROR for result in completed)
    durations = sorted(
        result.duration_ms for result in completed if result.duration_ms is not None
    )
    grader_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for result in completed:
        for grader in result.grader_results:
            if grader.outcome == GraderOutcome.ERROR:
                continue
            bucket = grader_counts[grader.grader_type.value]
            bucket[1] += 1
            if grader.outcome == GraderOutcome.PASS:
                bucket[0] += 1
    metrics = {
        grader_type: GraderMetric(
            passed=counts[0],
            total=counts[1],
            pass_rate=counts[0] / counts[1] if counts[1] else None,
        )
        for grader_type, counts in sorted(grader_counts.items())
    }
    executed = len(completed)
    p95_index = ceil(0.95 * len(durations)) - 1 if durations else None
    return EvaluationAggregate(
        total_cases=total_cases,
        completed_cases=executed,
        passed_cases=passed,
        failed_cases=failed,
        error_cases=errors,
        pass_rate=passed / executed if executed else None,
        average_duration_ms=(
            round(sum(durations) / len(durations), 2) if durations else None
        ),
        p95_duration_ms=durations[p95_index] if p95_index is not None else None,
        grader_metrics=metrics,
    )
