from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.domain.contracts import ToolCall, ToolResult, ToolResultStatus, ToolSpec
from app.domain.errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolValidationError,
)
from app.tools.calculator import calculate


class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200)


class CalculatorOutput(BaseModel):
    result: str = Field(max_length=2_000)


ToolHandler = Callable[[BaseModel], Awaitable[BaseModel | dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: float
    permissions: frozenset[str]
    output_limit: int

    def as_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
            output_schema=self.output_schema.model_json_schema(),
            timeout_seconds=self.timeout_seconds,
            permissions=sorted(self.permissions),
        )


@dataclass(frozen=True)
class Tool:
    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        definitions: dict[str, Tool] = {}
        for tool in tools:
            name = tool.definition.name
            if name in definitions:
                raise ValueError(f"Tool '{name}' is registered more than once.")
            if tool.definition.timeout_seconds <= 0:
                raise ValueError(f"Tool '{name}' must declare a positive timeout.")
            if tool.definition.output_limit <= 0:
                raise ValueError(f"Tool '{name}' must declare a positive output limit.")
            definitions[name] = tool
        self._tools = definitions

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc

    def specs(self, names: list[str]) -> list[ToolSpec]:
        return [self.get(name).definition.as_spec() for name in names]

    @property
    def names(self) -> set[str]:
        return set(self._tools)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def execute(self, call: ToolCall, granted_permissions: set[str]) -> ToolResult:
        tool = self._registry.get(call.name)
        definition = tool.definition
        missing_permissions = definition.permissions - granted_permissions
        if missing_permissions:
            missing = ", ".join(sorted(missing_permissions))
            raise ToolPermissionError(
                f"Tool '{call.name}' requires permissions that were not granted: {missing}."
            )
        try:
            validated_input = definition.input_schema.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolValidationError(f"Invalid arguments for '{call.name}'.") from exc

        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            raw_output = await asyncio.wait_for(
                tool.handler(validated_input),
                timeout=definition.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ToolExecutionError(f"Tool '{call.name}' timed out.") from exc
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool '{call.name}' failed.") from exc

        try:
            output = definition.output_schema.model_validate(raw_output)
        except ValidationError as exc:
            raise ToolExecutionError(f"Tool '{call.name}' returned invalid output.") from exc
        serialized = json.dumps(output.model_dump(mode="json"), ensure_ascii=False)
        if len(serialized) > definition.output_limit:
            raise ToolExecutionError(f"Tool '{call.name}' output exceeded its limit.")
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            status=ToolResultStatus.COMPLETED,
            output=output.model_dump(mode="json"),
            latency_ms=round((loop.time() - started) * 1000, 2),
        )


def default_tool_registry(extra_tools: list[Tool] | None = None) -> ToolRegistry:
    async def calculator_handler(payload: BaseModel) -> CalculatorOutput:
        calculator_input = CalculatorInput.model_validate(payload.model_dump())
        return CalculatorOutput(result=calculate(calculator_input.expression))

    tools = [
        Tool(
            definition=ToolDefinition(
                name="calculator",
                description=(
                    "Safely evaluate arithmetic using +, -, *, /, unary signs, and parentheses."
                ),
                input_schema=CalculatorInput,
                output_schema=CalculatorOutput,
                timeout_seconds=2.0,
                permissions=frozenset({"compute"}),
                output_limit=2_000,
            ),
            handler=calculator_handler,
        )
    ]
    tools.extend(extra_tools or [])
    return ToolRegistry(tools)
