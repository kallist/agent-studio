from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.contracts import ToolCall
from app.domain.errors import ToolExecutionError, ToolPermissionError, ToolValidationError
from app.tools.registry import (
    Tool,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    default_tool_registry,
)


class InputModel(BaseModel):
    value: str


class OutputModel(BaseModel):
    value: str


def make_tool(
    handler: Any,
    *,
    timeout: float = 0.1,
    output_limit: int = 100,
) -> Tool:
    return Tool(
        definition=ToolDefinition(
            name="test_tool",
            description="A controlled test tool.",
            input_schema=InputModel,
            output_schema=OutputModel,
            timeout_seconds=timeout,
            permissions=frozenset({"test:execute"}),
            output_limit=output_limit,
        ),
        handler=handler,
    )


def test_tool_definition_exposes_both_schemas_timeout_and_permissions() -> None:
    async def handler(payload: BaseModel) -> OutputModel:
        return OutputModel(value=InputModel.model_validate(payload).value)

    registry = ToolRegistry([make_tool(handler)])
    spec = registry.specs(["test_tool"])[0]

    assert spec.input_schema["properties"]["value"]["type"] == "string"
    assert spec.output_schema["properties"]["value"]["type"] == "string"
    assert spec.timeout_seconds == 0.1
    assert spec.permissions == ["test:execute"]


@pytest.mark.asyncio
async def test_tool_executor_enforces_permissions() -> None:
    called = False

    async def handler(payload: BaseModel) -> OutputModel:
        nonlocal called
        called = True
        return OutputModel(value=InputModel.model_validate(payload).value)

    executor = ToolExecutor(ToolRegistry([make_tool(handler)]))

    with pytest.raises(ToolPermissionError, match="not granted"):
        await executor.execute(ToolCall(name="test_tool", arguments={"value": "x"}), set())
    assert called is False


@pytest.mark.asyncio
async def test_tool_executor_enforces_timeout() -> None:
    async def handler(payload: BaseModel) -> OutputModel:
        del payload
        await asyncio.sleep(1)
        return OutputModel(value="late")

    executor = ToolExecutor(ToolRegistry([make_tool(handler, timeout=0.01)]))

    with pytest.raises(ToolExecutionError, match="timed out"):
        await executor.execute(
            ToolCall(name="test_tool", arguments={"value": "x"}), {"test:execute"}
        )


@pytest.mark.asyncio
async def test_tool_executor_validates_output_schema_and_size() -> None:
    async def invalid_handler(payload: BaseModel) -> dict[str, int]:
        del payload
        return {"unexpected": 1}

    invalid_executor = ToolExecutor(ToolRegistry([make_tool(invalid_handler)]))
    with pytest.raises(ToolExecutionError, match="invalid output"):
        await invalid_executor.execute(
            ToolCall(name="test_tool", arguments={"value": "x"}), {"test:execute"}
        )

    async def large_handler(payload: BaseModel) -> OutputModel:
        del payload
        return OutputModel(value="x" * 100)

    large_executor = ToolExecutor(ToolRegistry([make_tool(large_handler, output_limit=20)]))
    with pytest.raises(ToolExecutionError, match="exceeded"):
        await large_executor.execute(
            ToolCall(name="test_tool", arguments={"value": "x"}), {"test:execute"}
        )


@pytest.mark.asyncio
async def test_tool_executor_rejects_oversized_input_before_handler() -> None:
    called = False

    async def handler(payload: BaseModel) -> OutputModel:
        nonlocal called
        called = True
        return OutputModel(value=InputModel.model_validate(payload).value)

    executor = ToolExecutor(ToolRegistry([make_tool(handler)]))

    with pytest.raises(ToolValidationError, match="input exceeded"):
        await executor.execute(
            ToolCall(name="test_tool", arguments={"value": "x" * 20_000}),
            {"test:execute"},
        )
    assert called is False


@pytest.mark.asyncio
async def test_calculator_schema_rejects_unexpected_arguments() -> None:
    executor = ToolExecutor(default_tool_registry())

    with pytest.raises(ToolValidationError, match="Invalid arguments"):
        await executor.execute(
            ToolCall(
                name="calculator",
                arguments={"expression": "1 + 1", "fallback": "__import__('os')"},
            ),
            {"compute"},
        )
