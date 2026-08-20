from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.contracts import AgentEvent, RunObservability, RunResult, RunStatus
from app.evaluation.contracts import (
    EvaluationCaseStatus,
    GraderConfig,
    GraderOutcome,
    GraderResultDraft,
    GraderType,
)


@dataclass(frozen=True)
class EvaluationContext:
    run: RunResult
    events: list[AgentEvent]
    observability: RunObservability


class DeterministicGrader:
    """Grades persisted application facts without model or provider calls."""

    def grade(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        handler = {
            GraderType.RUN_STATUS: self._run_status,
            GraderType.FINAL_OUTPUT_NON_EMPTY: self._final_output_non_empty,
            GraderType.EXACT_MATCH: self._exact_match,
            GraderType.CONTAINS: self._contains,
            GraderType.TOOL_SELECTED: self._tool_selected,
            GraderType.TOOL_NOT_SELECTED: self._tool_not_selected,
            GraderType.RETRIEVAL_HIT: self._retrieval_hit,
            GraderType.CITATION: self._citation,
            GraderType.MEMORY_RETRIEVED: self._memory_retrieved,
            GraderType.MAX_STEPS: self._max_steps,
            GraderType.MAX_DURATION: self._max_duration,
        }[config.type]
        return handler(config, context)

    def _result(
        self,
        config: GraderConfig,
        passed: bool,
        message: str,
        *,
        expected: Any,
        actual: Any,
        evidence: list[dict[str, Any]] | None = None,
    ) -> GraderResultDraft:
        return GraderResultDraft(
            grader_type=config.type,
            required=config.required,
            outcome=GraderOutcome.PASS if passed else GraderOutcome.FAIL,
            passed=passed,
            score=1.0 if passed else 0.0,
            message=message,
            expected=expected,
            actual=actual,
            evidence=evidence or [],
        )

    def _error(
        self,
        config: GraderConfig,
        message: str,
        *,
        expected: Any,
        actual: Any,
    ) -> GraderResultDraft:
        return GraderResultDraft(
            grader_type=config.type,
            required=config.required,
            outcome=GraderOutcome.ERROR,
            passed=None,
            score=None,
            message=message,
            expected=expected,
            actual=actual,
        )

    def _run_status(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        expected = config.expected_status or RunStatus.COMPLETED
        passed = context.run.status == expected
        return self._result(
            config,
            passed,
            f"Run status was {context.run.status.value}; expected {expected.value}.",
            expected=expected.value,
            actual=context.run.status.value,
            evidence=self._terminal_evidence(context.events),
        )

    def _final_output_non_empty(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        output = context.run.output or ""
        passed = bool(output.strip())
        return self._result(
            config,
            passed,
            "Final output was non-empty." if passed else "Final output was empty.",
            expected={"non_empty": True},
            actual={"non_empty": passed, "length": len(output)},
            evidence=self._terminal_evidence(context.events),
        )

    def _exact_match(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        expected = config.value or ""
        actual = context.run.output or ""
        passed = self._normalize(actual, config.case_sensitive) == self._normalize(
            expected, config.case_sensitive
        )
        return self._result(
            config,
            passed,
            "Final output matched exactly after configured normalization."
            if passed
            else "Final output did not match exactly after configured normalization.",
            expected={"value": expected, "case_sensitive": config.case_sensitive},
            actual=actual,
            evidence=self._terminal_evidence(context.events),
        )

    def _contains(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        expected = config.value or ""
        actual = context.run.output or ""
        needle = self._normalize(expected, config.case_sensitive)
        haystack = self._normalize(actual, config.case_sensitive)
        passed = needle in haystack
        return self._result(
            config,
            passed,
            f"Final output {'contained' if passed else 'did not contain'} the expected text.",
            expected={"contains": expected, "case_sensitive": config.case_sensitive},
            actual=actual,
            evidence=self._terminal_evidence(context.events),
        )

    def _tool_selected(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        selected = self._selected_tools(context.events)
        passed = config.tool_name in [name for name, _event in selected]
        return self._result(
            config,
            passed,
            f"Tool '{config.tool_name}' {'was' if passed else 'was not'} selected.",
            expected={"selected": config.tool_name},
            actual={"selected_tools": [name for name, _event in selected]},
            evidence=[
                self._event_ref(event)
                for name, event in selected
                if name == config.tool_name
            ],
        )

    def _tool_not_selected(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        selected = self._selected_tools(context.events)
        offending = [event for name, event in selected if name == config.tool_name]
        passed = not offending
        return self._result(
            config,
            passed,
            f"Tool '{config.tool_name}' {'was not' if passed else 'was unexpectedly'} selected.",
            expected={"not_selected": config.tool_name},
            actual={"selected_tools": [name for name, _event in selected]},
            evidence=[self._event_ref(event) for event in offending],
        )

    def _retrieval_hit(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        citations = self._knowledge_citations(context.events)
        matched = self._matching_citations(config, citations)
        passed = bool(matched)
        return self._result(
            config,
            passed,
            "Knowledge retrieval returned the expected evidence."
            if passed
            else "Knowledge retrieval did not return the expected evidence.",
            expected=self._citation_expectation(config),
            actual={"results": [item for item, _event in citations]},
            evidence=[self._event_ref(event) for _item, event in matched],
        )

    def _citation(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        citations = self._knowledge_citations(context.events)
        matched = self._matching_citations(config, citations)
        passed = bool(matched)
        return self._result(
            config,
            passed,
            "Citation provenance included the expected source."
            if passed
            else "Citation provenance did not include the expected source.",
            expected={"citation_present": True, **self._citation_expectation(config)},
            actual={"citations": [item for item, _event in citations]},
            evidence=[self._event_ref(event) for _item, event in matched],
        )

    def _memory_retrieved(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        matched = [
            event
            for event in context.events
            if event.type == "memory.retrieved"
            and isinstance(event.payload.get("count"), int)
            and int(event.payload["count"]) > 0
        ]
        passed = bool(matched)
        return self._result(
            config,
            passed,
            "Durable memory was retrieved." if passed else "No durable memory was retrieved.",
            expected={"memory_retrieved": True},
            actual={"memory_retrieved": passed},
            evidence=[self._event_ref(event) for event in matched],
        )

    def _max_steps(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        maximum = int(config.maximum or 0)
        actual = context.observability.step_count
        passed = actual <= maximum
        return self._result(
            config,
            passed,
            f"Step count {actual} {'was within' if passed else 'exceeded'} the maximum {maximum}.",
            expected={"maximum": maximum},
            actual={"step_count": actual},
            evidence=self._terminal_evidence(context.events),
        )

    def _max_duration(
        self, config: GraderConfig, context: EvaluationContext
    ) -> GraderResultDraft:
        maximum = config.maximum or 0
        actual = context.observability.duration_ms
        if actual is None:
            return self._error(
                config,
                "Run duration is unavailable; the latency grader cannot decide.",
                expected={"maximum_ms": maximum},
                actual={"duration_ms": None},
            )
        passed = actual <= maximum
        return self._result(
            config,
            passed,
            (
                f"Duration {actual:g} ms "
                f"{'was within' if passed else 'exceeded'} the maximum {maximum:g} ms."
            ),
            expected={"maximum_ms": maximum},
            actual={"duration_ms": actual},
            evidence=self._terminal_evidence(context.events),
        )

    @staticmethod
    def _normalize(value: str, case_sensitive: bool) -> str:
        trimmed = value.strip()
        return trimmed if case_sensitive else trimmed.casefold()

    @staticmethod
    def _event_ref(event: AgentEvent) -> dict[str, Any]:
        return {
            "kind": "run_event",
            "run_id": str(event.run_id),
            "event_id": str(event.event_id),
            "sequence": event.sequence,
            "event_type": event.type,
        }

    def _terminal_evidence(self, events: list[AgentEvent]) -> list[dict[str, Any]]:
        terminal = next(
            (
                event
                for event in reversed(events)
                if event.type in {"run.completed", "run.failed", "run.cancelled"}
            ),
            None,
        )
        return [self._event_ref(terminal)] if terminal is not None else []

    @staticmethod
    def _selected_tools(events: list[AgentEvent]) -> list[tuple[str, AgentEvent]]:
        selected: list[tuple[str, AgentEvent]] = []
        for event in events:
            if event.type != "tool.selected":
                continue
            name = event.payload.get("tool")
            if isinstance(name, str):
                selected.append((name, event))
        return selected

    @staticmethod
    def _knowledge_citations(
        events: list[AgentEvent],
    ) -> list[tuple[dict[str, Any], AgentEvent]]:
        citations: list[tuple[dict[str, Any], AgentEvent]] = []
        for event in events:
            if event.type != "tool.completed" or event.payload.get("tool") != "knowledge_search":
                continue
            result = event.payload.get("result")
            if not isinstance(result, dict):
                continue
            items = result.get("results")
            if not isinstance(items, list):
                continue
            citations.extend((item, event) for item in items if isinstance(item, dict))
        return citations

    @staticmethod
    def _citation_expectation(config: GraderConfig) -> dict[str, Any]:
        expected: dict[str, Any] = {}
        if config.expected_source is not None:
            expected["source"] = config.expected_source
        if config.expected_document_id is not None:
            expected["document_id"] = str(config.expected_document_id)
        return expected

    @staticmethod
    def _matching_citations(
        config: GraderConfig,
        citations: list[tuple[dict[str, Any], AgentEvent]],
    ) -> list[tuple[dict[str, Any], AgentEvent]]:
        matched: list[tuple[dict[str, Any], AgentEvent]] = []
        for item, event in citations:
            if config.expected_source is not None and item.get("source") != config.expected_source:
                continue
            if config.expected_document_id is not None:
                if item.get("document_id") != str(config.expected_document_id):
                    continue
            matched.append((item, event))
        return matched


def case_status(results: list[GraderResultDraft]) -> EvaluationCaseStatus:
    required = [result for result in results if result.required]
    if any(result.outcome == GraderOutcome.ERROR for result in required):
        return EvaluationCaseStatus.ERROR
    if any(result.outcome == GraderOutcome.FAIL for result in required):
        return EvaluationCaseStatus.FAIL
    return EvaluationCaseStatus.PASS
