from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from agents import (
    Model,
    ModelSettings,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
)
from openai import AsyncOpenAI

from app.domain.contracts import AgentContext, AgentDecision, ModelApiStyle, ToolCall
from app.domain.errors import ProviderNotConfiguredError


class DecisionProvider(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def decide(self, context: AgentContext) -> object: ...


@dataclass(frozen=True)
class MockProvider:
    """Deterministic decision provider for tests and the calculator demo."""

    name: str = "mock"
    blocking_input: str | None = None

    @property
    def is_configured(self) -> bool:
        return True

    async def decide(self, context: AgentContext) -> AgentDecision:
        if self.blocking_input is not None and context.user_input == self.blocking_input:
            await asyncio.Event().wait()
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
class ModelCapabilities:
    tool_calling: bool
    structured_output: bool
    reasoning_configuration: bool
    streaming: bool
    usage: bool
    responses_only_fields: bool
    strict_tool_schema: bool
    max_tool_name_length: int


@dataclass(frozen=True)
class ResolvedProviderModel:
    provider: str
    api_style: ModelApiStyle
    model_name: str
    client: AsyncOpenAI
    sdk_model: Model
    model_settings: ModelSettings
    capabilities: ModelCapabilities


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def api_style(self) -> ModelApiStyle: ...

    @property
    def api_key(self) -> str | None: ...

    @property
    def default_model(self) -> str | None: ...

    @property
    def tracing_disabled(self) -> bool: ...

    @property
    def capabilities(self) -> ModelCapabilities: ...

    @property
    def is_configured(self) -> bool: ...

    @property
    def not_configured_message(self) -> str: ...

    @property
    def tracing_export_api_key(self) -> str | None: ...

    def resolve(self, requested_model: str | None) -> ResolvedProviderModel: ...


@dataclass(frozen=True)
class OpenAIProvider:
    name = "openai"
    display_name = "OpenAI"
    api_style = ModelApiStyle.RESPONSES
    capabilities = ModelCapabilities(
        tool_calling=True,
        structured_output=True,
        reasoning_configuration=True,
        streaming=True,
        usage=True,
        responses_only_fields=True,
        strict_tool_schema=True,
        max_tool_name_length=64,
    )

    api_key: str | None
    default_model: str | None
    tracing_disabled: bool = True
    request_timeout_seconds: float = 20.0
    max_retries: int = 2
    max_output_tokens: int = 512

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    @property
    def not_configured_message(self) -> str:
        return "OpenAI provider is not configured."

    @property
    def tracing_export_api_key(self) -> str | None:
        return None if self.tracing_disabled else self.api_key

    def resolve(self, requested_model: str | None) -> ResolvedProviderModel:
        model_name = _resolve_model_name(self, requested_model, "OPENAI_MODEL")
        if self.api_key is None:
            raise ProviderNotConfiguredError(self.not_configured_message)
        client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        return ResolvedProviderModel(
            provider=self.name,
            api_style=self.api_style,
            model_name=model_name,
            client=client,
            sdk_model=OpenAIResponsesModel(model=model_name, openai_client=client),
            model_settings=ModelSettings(
                max_tokens=self.max_output_tokens,
                parallel_tool_calls=False,
                truncation="disabled",
                store=False,
                include_usage=True,
                preserve_raw_usage=False,
            ),
            capabilities=self.capabilities,
        )


@dataclass(frozen=True)
class DeepSeekProvider:
    name = "deepseek"
    display_name = "DeepSeek"
    api_style = ModelApiStyle.CHAT_COMPLETIONS
    capabilities = ModelCapabilities(
        tool_calling=True,
        structured_output=True,
        reasoning_configuration=True,
        streaming=True,
        usage=True,
        responses_only_fields=False,
        # DeepSeek strict function schemas require its beta endpoint. The stable
        # first-class path stays on application-side argument validation.
        strict_tool_schema=False,
        max_tool_name_length=64,
    )

    api_key: str | None
    default_model: str | None
    base_url: str = "https://api.deepseek.com"
    tracing_disabled: bool = True
    request_timeout_seconds: float = 20.0
    max_retries: int = 2
    max_output_tokens: int = 512

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    @property
    def not_configured_message(self) -> str:
        return "DeepSeek provider is not configured."

    @property
    def tracing_export_api_key(self) -> None:
        # DeepSeek credentials must never be used for OpenAI SDK trace export.
        return None

    def resolve(self, requested_model: str | None) -> ResolvedProviderModel:
        model_name = _resolve_model_name(self, requested_model, "DEEPSEEK_MODEL")
        if self.api_key is None:
            raise ProviderNotConfiguredError(self.not_configured_message)
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        return ResolvedProviderModel(
            provider=self.name,
            api_style=self.api_style,
            model_name=model_name,
            client=client,
            sdk_model=OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
                strict_feature_validation=True,
                buffer_streamed_tool_calls=True,
            ),
            # DeepSeek thinking is deliberately disabled for this bounded v1
            # path. It is not inferred from OpenAI reasoning settings.
            model_settings=ModelSettings(
                max_tokens=self.max_output_tokens,
                parallel_tool_calls=False,
                include_usage=True,
                preserve_raw_usage=False,
                extra_body={"thinking": {"type": "disabled"}},
            ),
            capabilities=self.capabilities,
        )


def _resolve_model_name(
    provider: LLMProvider, requested_model: str | None, environment_name: str
) -> str:
    if not provider.is_configured:
        raise ProviderNotConfiguredError(provider.not_configured_message)
    model_name = requested_model or provider.default_model
    if model_name is None or not model_name.strip():
        raise ProviderNotConfiguredError(
            f"{provider.display_name} model is not configured; set it on the agent or "
            f"{environment_name}."
        )
    return model_name.strip()


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
