from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.domain.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError
from app.tools.calculator import calculate


class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel], str]
    timeout_seconds: float = 2.0
    output_limit: int = 2_000
    side_effects: bool = False


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc

    @property
    def names(self) -> set[str]:
        return set(self._definitions)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        definition = self._registry.get(name)
        try:
            validated = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError(f"Invalid arguments for '{name}'.") from exc
        try:
            output = await asyncio.wait_for(
                asyncio.to_thread(definition.handler, validated),
                timeout=definition.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ToolExecutionError(f"Tool '{name}' timed out.") from exc
        if len(output) > definition.output_limit:
            raise ToolExecutionError(f"Tool '{name}' output exceeded its limit.")
        return output


def default_tool_registry() -> ToolRegistry:
    def calculator_handler(payload: BaseModel) -> str:
        calculator_input = CalculatorInput.model_validate(payload.model_dump())
        return calculate(calculator_input.expression)

    return ToolRegistry(
        [
            ToolDefinition(
                name="calculator",
                description="Safely evaluate arithmetic using +, -, *, /, and parentheses.",
                input_model=CalculatorInput,
                handler=calculator_handler,
            )
        ]
    )
