from __future__ import annotations

from dataclasses import dataclass

from agents import OpenAIResponsesModel
from openai import AsyncOpenAI


@dataclass(frozen=True)
class MockProvider:
    """Marker for deterministic local execution with no credential."""

    name: str = "mock"


@dataclass(frozen=True)
class OpenAIProvider:
    api_key: str | None
    default_model: str
    tracing_disabled: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def build_model(self, model_name: str | None = None) -> OpenAIResponsesModel:
        if not self.is_configured or self.api_key is None:
            raise ValueError("OpenAI provider is not configured.")
        return OpenAIResponsesModel(
            model=model_name or self.default_model,
            openai_client=AsyncOpenAI(api_key=self.api_key),
        )
