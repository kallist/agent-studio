from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.contracts import (
    AgentDefinition,
    AgentEvent,
    RuntimeInput,
    RuntimeLimits,
    RuntimeMode,
    TerminationReason,
)
from app.main import create_app
from app.persistence.database import settings
from app.runtime.agents_sdk import AgentsSdkRuntime
from app.runtime.providers import DeepSeekProvider
from app.tools.registry import ToolExecutor, default_tool_registry

pytestmark = [pytest.mark.real_deepseek, pytest.mark.asyncio]


def _credentials() -> tuple[str, str]:
    if os.getenv("RUN_REAL_DEEPSEEK_TESTS") != "1":
        pytest.skip("Real DeepSeek tests require RUN_REAL_DEEPSEEK_TESTS=1.")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        pytest.skip("Real DeepSeek: BLOCKED — DEEPSEEK_API_KEY not configured")
    model = (
        os.getenv("DEEPSEEK_REAL_TEST_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or "deepseek-v4-flash"
    )
    return key, model


def _agent(model: str, *, tools: list[str], instructions: str) -> AgentDefinition:
    return AgentDefinition(
        id=uuid4(),
        name="Real DeepSeek validation",
        instructions=instructions,
        runtime_mode=RuntimeMode.DEEPSEEK,
        model=model,
        tools=tools,
        memory_enabled=False,
        created_at=datetime.now(UTC),
    )


def _runtime(key: str) -> AgentsSdkRuntime:
    return AgentsSdkRuntime(
        DeepSeekProvider(
            api_key=key,
            default_model=None,
            request_timeout_seconds=30,
            max_retries=1,
            max_output_tokens=128,
        ),
        ToolExecutor(default_tool_registry()),
    )


@pytest.fixture
async def real_deepseek_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, str]]:
    key, model = _credentials()
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", key)
    monkeypatch.setattr(settings, "deepseek_model", model)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "deepseek_request_timeout_seconds", 30)
    monkeypatch.setattr(settings, "deepseek_max_retries", 1)
    monkeypatch.setattr(settings, "deepseek_max_output_tokens", 128)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'real-deepseek.db').as_posix()}",
        knowledge_storage_path=str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, model


async def _wait_run(client: AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(1_200):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.05)
    pytest.fail("Real DeepSeek Run did not reach a terminal state.")


async def _create_api_agent(
    client: AsyncClient,
    model: str,
    *,
    name: str,
    instructions: str,
    tools: list[str],
    knowledge_base_ids: list[str] | None = None,
    memory_enabled: bool = False,
) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "instructions": instructions,
            "runtime_mode": "deepseek",
            "model": model,
            "tools": tools,
            "knowledge_base_ids": knowledge_base_ids or [],
            "memory_enabled": memory_enabled,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _run_api_agent(
    client: AsyncClient, agent_id: object, user_input: str
) -> dict[str, object]:
    accepted = await client.post(
        f"/agents/{agent_id}/runs", json={"input": user_input}
    )
    assert accepted.status_code == 202, accepted.text
    return await _wait_run(client, accepted.json()["id"])


async def test_real_deepseek_basic_chat_stream_usage_and_identity() -> None:
    key, model = _credentials()
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    result = await _runtime(key).run(
        RuntimeInput(
            run_id=uuid4(),
            agent=_agent(
                model,
                tools=[],
                instructions="Reply with exactly REAL_DEEPSEEK_OK and nothing else.",
            ),
            user_input="Return the validation token now.",
            limits=RuntimeLimits(
                max_steps=2,
                timeout_seconds=60,
                invalid_output_retries=0,
            ),
        ),
        collect,
    )

    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.final_output == "REAL_DEEPSEEK_OK"
    completed = [event for event in events if event.type == "llm.completed"]
    assert len(completed) == 1
    assert completed[0].payload["provider"] == "deepseek"
    assert completed[0].payload["api_style"] == "chat_completions"
    assert completed[0].payload["model"] == model
    assert completed[0].payload["stream_events"] > 0
    assert completed[0].usage is not None
    assert completed[0].usage.requests == 1
    assert completed[0].usage.input_tokens is not None
    assert completed[0].usage.output_tokens is not None
    assert completed[0].usage.total_tokens is not None


async def test_real_deepseek_calculator_is_model_selected_then_application_executed(
    real_deepseek_client: tuple[AsyncClient, str],
) -> None:
    client, model = real_deepseek_client
    agent = await _create_api_agent(
        client,
        model,
        name="Real DeepSeek calculator",
        instructions=(
            "For every arithmetic request call calculator exactly once, then return only "
            "its exact result."
        ),
        tools=["calculator"],
    )
    run = await _run_api_agent(
        client, agent["id"], "Use the calculator tool to compute: 128 * 37 + 456"
    )

    assert run["status"] == "completed"
    assert "5192" in str(run["output"])
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    assert [event["type"] for event in events].count("tool.selected") == 1
    tool_completed = [event for event in events if event["type"] == "tool.completed"]
    assert len(tool_completed) == 1
    assert tool_completed[0]["payload"]["result"] == {"result": "5192"}
    llm_completed = [event for event in events if event["type"] == "llm.completed"]
    assert len(llm_completed) == 2
    assert all(event["payload"]["provider"] == "deepseek" for event in llm_completed)
    assert all(
        event["payload"]["api_style"] == "chat_completions"
        for event in llm_completed
    )
    observability = (await client.get(f"/runs/{run['id']}/observability")).json()
    assert observability["runtime_type"] == "agents_sdk"
    assert observability["provider_type"] == "deepseek"
    assert observability["api_style"] == "chat_completions"
    assert observability["model"] == model
    assert observability["usage"]["requests"] == 2
    assert observability["usage"]["input_tokens"] > 0
    assert observability["usage"]["output_tokens"] > 0
    assert observability["usage"]["total_tokens"] > 0


async def test_real_deepseek_rag_uses_completed_ingestion_and_citations(
    real_deepseek_client: tuple[AsyncClient, str],
) -> None:
    client, model = real_deepseek_client
    base_response = await client.post(
        "/knowledge-bases",
        json={"name": "Real DeepSeek RAG", "description": "Online validation"},
    )
    assert base_response.status_code == 201
    base = base_response.json()
    upload = await client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={
            "file": (
                "validation.txt",
                b"Parser failures must be isolated and surfaced as bounded safe errors.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 202
    job_id = upload.json()["ingestion_job"]["id"]
    for _ in range(300):
        job = (await client.get(f"/ingestion-jobs/{job_id}")).json()
        if job["state"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert job["state"] == "completed"

    rag_agent = await _create_api_agent(
        client,
        model,
        name="Real DeepSeek RAG",
        instructions=(
            "For parser policy questions call knowledge_search exactly once, then answer from "
            "the cited result."
        ),
        tools=["knowledge_search"],
        knowledge_base_ids=[base["id"]],
    )
    rag_run = await _run_api_agent(
        client,
        rag_agent["id"],
        "How must parser failures be handled?",
    )
    assert rag_run["status"] == "completed"
    assert "isolat" in str(rag_run["output"]).casefold()
    rag_events = (await client.get(f"/runs/{rag_run['id']}/events")).json()
    knowledge_event = next(
        event
        for event in rag_events
        if event["type"] == "tool.completed"
        and event["payload"]["tool"] == "knowledge_search"
    )
    assert knowledge_event["payload"]["result"]["results"][0]["document"] == (
        "validation.txt"
    )


async def test_real_deepseek_memory_write_and_retrieval_use_product_path(
    real_deepseek_client: tuple[AsyncClient, str],
) -> None:
    client, model = real_deepseek_client
    memory_agent = await _create_api_agent(
        client,
        model,
        name="Real DeepSeek Memory",
        instructions="Use relevant durable memory facts when answering the user.",
        tools=[],
        memory_enabled=True,
    )
    remembered = await _run_api_agent(
        client,
        memory_agent["id"],
        "Remember that my project codename is cedar-east.",
    )
    assert remembered["status"] == "completed"
    remembered_events = (
        await client.get(f"/runs/{remembered['id']}/events")
    ).json()
    assert any(event["type"] == "memory.written" for event in remembered_events)

    recalled = await _run_api_agent(
        client,
        memory_agent["id"],
        "What is my project codename?",
    )
    assert recalled["status"] == "completed"
    assert "cedar-east" in str(recalled["output"]).casefold()
    recalled_events = (
        await client.get(f"/runs/{recalled['id']}/events")
    ).json()
    assert any(event["type"] == "memory.retrieved" for event in recalled_events)


async def test_real_deepseek_evaluation_uses_linked_evaluation_run(
    real_deepseek_client: tuple[AsyncClient, str],
) -> None:
    client, model = real_deepseek_client

    evaluation_agent = await _create_api_agent(
        client,
        model,
        name="Real DeepSeek Evaluation",
        instructions=(
            "For arithmetic always call calculator exactly once, then return only its result."
        ),
        tools=["calculator"],
    )
    suite_response = await client.post(
        "/evaluation-suites",
        json={
            "name": "Real DeepSeek calculator evaluation",
            "agent_id": evaluation_agent["id"],
            "cases": [
                {
                    "name": "True DeepSeek tool call",
                    "input": "Use the calculator tool to compute: 128 * 37 + 456",
                    "graders": [
                        {"type": "run_status"},
                        {"type": "final_output_non_empty"},
                        {"type": "contains", "value": "5192"},
                        {"type": "tool_selected", "tool_name": "calculator"},
                        {"type": "max_steps", "maximum": 3},
                    ],
                }
            ],
        },
    )
    assert suite_response.status_code == 201, suite_response.text
    accepted = await client.post(
        f"/evaluation-suites/{suite_response.json()['id']}/runs",
        headers={"Idempotency-Key": "real-deepseek-evaluation-1"},
    )
    assert accepted.status_code == 202
    evaluation_id = accepted.json()["id"]
    for _ in range(1_200):
        evaluation = (await client.get(f"/evaluation-runs/{evaluation_id}")).json()
        if evaluation["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.05)
    assert evaluation["status"] == "completed"
    assert evaluation["passed_cases"] == 1
    results = (
        await client.get(f"/evaluation-runs/{evaluation_id}/results")
    ).json()
    assert results[0]["status"] == "pass"
    assert results[0]["run_id"]
    evaluation_run = await client.get(f"/runs/{results[0]['run_id']}")
    assert evaluation_run.status_code == 200
    assert evaluation_run.json()["run_kind"] == "evaluation"

    dashboard = (await client.get("/observability/dashboard")).json()
    assert all(
        item["run_id"] != results[0]["run_id"] for item in dashboard["recent_runs"]
    )
