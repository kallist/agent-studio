from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.runtime.providers import MockProvider


async def create_agent(
    client: AsyncClient, runtime_mode: str = "mock", tools: list[str] | None = None
) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": "Calculator Agent",
            "instructions": "Use the calculator for arithmetic.",
            "runtime_mode": runtime_mode,
            "tools": ["calculator"] if tools is None else tools,
        },
    )
    assert response.status_code == 201
    return response.json()


async def wait_for_terminal(client: AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("run did not reach a terminal status")


@pytest.mark.asyncio
async def test_create_list_run_retrieve_and_persist_trace(client: AsyncClient) -> None:
    created = await create_agent(client)
    listed = await client.get("/agents")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created["id"]]

    accepted = await client.post(
        f"/agents/{created['id']}/runs", json={"input": "计算 128 * 37 + 456"}
    )
    assert accepted.status_code == 202
    run = await wait_for_terminal(client, accepted.json()["id"])
    assert run["status"] == "completed"
    assert run["output"] == "5192"

    events_response = await client.get(f"/runs/{run['id']}/events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert [event["sequence"] for event in events] == list(range(1, 14))
    assert [event["type"] for event in events] == [
        "run.started",
        "step.started",
        "llm.started",
        "llm.completed",
        "tool.selected",
        "tool.started",
        "tool.completed",
        "step.completed",
        "step.started",
        "llm.started",
        "llm.completed",
        "step.completed",
        "run.completed",
    ]
    assert events[6]["payload"]["result"] == {"result": "5192"}
    assert events[-1]["payload"]["termination_reason"] == "completed"


@pytest.mark.asyncio
async def test_invalid_agent_and_run_return_not_found(client: AsyncClient) -> None:
    missing = uuid4()
    assert (await client.get(f"/agents/{missing}")).status_code == 404
    assert (await client.post(f"/agents/{missing}/runs", json={"input": "1+1"})).status_code == 404
    assert (await client.get(f"/runs/{missing}")).status_code == 404
    assert (await client.post(f"/runs/{missing}/cancel")).status_code == 404


@pytest.mark.asyncio
async def test_openai_provider_is_explicitly_unavailable_without_key(client: AsyncClient) -> None:
    created = await create_agent(client, runtime_mode="openai")
    response = await client.post(f"/agents/{created['id']}/runs", json={"input": "1+1"})
    assert response.status_code == 503
    assert response.json()["detail"] == "OpenAI provider is not configured."


@pytest.mark.asyncio
async def test_tool_failure_is_persisted_with_reason(client: AsyncClient) -> None:
    created = await create_agent(client)
    accepted = await client.post(f"/agents/{created['id']}/runs", json={"input": "计算 1 / 0"})
    run = await wait_for_terminal(client, accepted.json()["id"])
    assert run["status"] == "failed"
    assert "Division by zero" in str(run["error"])
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    assert events[-3]["type"] == "tool.failed"
    assert events[-1]["type"] == "run.failed"
    assert events[-1]["payload"]["termination_reason"] == "tool_error"


@pytest.mark.asyncio
async def test_mock_runtime_respects_agent_tool_configuration(client: AsyncClient) -> None:
    created = await create_agent(client, tools=[])
    accepted = await client.post(
        f"/agents/{created['id']}/runs", json={"input": "Explain bounded loops"}
    )
    run = await wait_for_terminal(client, accepted.json()["id"])
    assert run["status"] == "completed"
    assert run["output"] == "Mock response: Explain bounded loops"
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    assert all(not event["type"].startswith("tool.") for event in events)


@pytest.mark.asyncio
async def test_user_can_cancel_an_in_flight_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def block_decision(self: MockProvider, context: object) -> object:
        del self, context
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(MockProvider, "decide", block_decision)
    created = await create_agent(client)
    accepted = await client.post(f"/agents/{created['id']}/runs", json={"input": "计算 1 + 1"})
    run_id = accepted.json()["id"]
    await asyncio.wait_for(started.wait(), timeout=1)

    cancelled = await client.post(f"/runs/{run_id}/cancel")
    assert cancelled.status_code == 202
    run = await wait_for_terminal(client, run_id)
    assert run["status"] == "cancelled"
    events = (await client.get(f"/runs/{run_id}/events")).json()
    assert events[-1]["type"] == "run.cancelled"
    assert events[-1]["payload"]["termination_reason"] == "cancelled"
