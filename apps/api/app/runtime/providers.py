from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.contracts import AgentContext, AgentDecision, ToolCall


class DecisionProvider(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def decide(self, context: AgentContext) -> object: ...


@dataclass(frozen=True)
class MockProvider:
    """Deterministic decision provider for tests and the calculator demo."""

    name: str = "mock"

    @property
    def is_configured(self) -> bool:
        return True

    async def decide(self, context: AgentContext) -> AgentDecision:
        if context.steps:
            result = context.steps[-1].tool_result
            if result is not None and result.output is not None:
                if result.tool_name == "knowledge_search":
                    raw_results = result.output.get("results")
                    if isinstance(raw_results, list) and raw_results:
                        first = raw_results[0]
                        if isinstance(first, dict):
                            content = str(first.get("content", ""))
                            document = str(first.get("document", "Source"))
                            source = str(first.get("source", ""))
                            return AgentDecision(
                                action="final",
                                final_output=(
                                    f"{content[:16_000]}\n\nSource: {document} ({source})"
                                ),
                            )
                    return AgentDecision(
                        action="final",
                        final_output="No relevant knowledge source was found.",
                    )
                final = result.output.get("result")
                if isinstance(final, str):
                    return AgentDecision(action="final", final_output=final)
                return AgentDecision(action="final", final_output=str(result.output))

        expression = _extract_arithmetic(context.user_input)
        available_tools = {tool.name for tool in context.tools}
        if expression is not None and "calculator" in available_tools:
            return AgentDecision(
                action="tool",
                tool_call=ToolCall(name="calculator", arguments={"expression": expression}),
            )
        if "knowledge_search" in available_tools:
            return AgentDecision(
                action="tool",
                tool_call=ToolCall(
                    name="knowledge_search",
                    arguments={"query": context.user_input, "top_k": 5},
                ),
            )
        if context.memory.long_term:
            return AgentDecision(
                action="final",
                final_output=f"I remember: {context.memory.long_term[0].record.content}",
            )
        return AgentDecision(
            action="final",
            final_output=f"Mock response: {context.user_input.strip()}",
        )


@dataclass(frozen=True)
class OpenAIProvider:
    api_key: str | None
    default_model: str
    tracing_disabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())


def _extract_arithmetic(user_input: str) -> str | None:
    """Find the longest arithmetic-looking span without parsing structured model output."""

    allowed = frozenset("0123456789+-*/(). \t\r\n")
    candidates: list[str] = []
    current: list[str] = []
    for character in user_input:
        if character in allowed:
            current.append(character)
            continue
        if current:
            candidates.append("".join(current).strip())
            current = []
    if current:
        candidates.append("".join(current).strip())

    operators = frozenset("+-*/")
    valid = [
        candidate
        for candidate in candidates
        if any(character.isdigit() for character in candidate)
        and any(character in operators for character in candidate)
    ]
    return max(valid, key=len) if valid else None
