from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient


async def create_agent(client: AsyncClient, runtime_mode: str = "mock") -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": "Calculator Agent",
            "instructions": "Use the calculator for arithmetic.",
            "runtime_mode": runtime_mode,
            "tools": ["calculator"],
        },
    )
    assert response.status_code == 201
    return response.json()


async def wait_for_terminal(client: AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed"}:
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
    assert [event["sequence"] for event in events] == list(range(1, 8))
    assert [event["type"] for event in events] == [
        "run.started",
        "llm.started",
        "tool.selected",
        "tool.started",
        "tool.completed",
        "llm.completed",
        "run.completed",
    ]
    assert events[4]["payload"]["result"] == "5192"


@pytest.mark.asyncio
async def test_invalid_agent_and_run_return_not_found(client: AsyncClient) -> None:
    missing = uuid4()
    assert (await client.get(f"/agents/{missing}")).status_code == 404
    assert (await client.post(f"/agents/{missing}/runs", json={"input": "1+1"})).status_code == 404
    assert (await client.get(f"/runs/{missing}")).status_code == 404


@pytest.mark.asyncio
async def test_openai_provider_is_explicitly_unavailable_without_key(client: AsyncClient) -> None:
    created = await create_agent(client, runtime_mode="openai")
    response = await client.post(f"/agents/{created['id']}/runs", json={"input": "1+1"})
    assert response.status_code == 503
    assert response.json()["detail"] == "OpenAI provider is not configured."


@pytest.mark.asyncio
async def test_tool_failure_is_persisted(client: AsyncClient) -> None:
    created = await create_agent(client)
    accepted = await client.post(f"/agents/{created['id']}/runs", json={"input": "计算 1 / 0"})
    run = await wait_for_terminal(client, accepted.json()["id"])
    assert run["status"] == "failed"
    assert "Division by zero" in str(run["error"])
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    assert events[-2]["type"] == "tool.failed"
    assert events[-1]["type"] == "run.failed"


@pytest.mark.asyncio
async def test_mock_runtime_respects_agent_tool_configuration(client: AsyncClient) -> None:
    response = await client.post(
        "/agents",
        json={
            "name": "No tools",
            "instructions": "Do not use tools.",
            "runtime_mode": "mock",
            "tools": [],
        },
    )
    accepted = await client.post(
        f"/agents/{response.json()['id']}/runs", json={"input": "计算 1 + 1"}
    )
    run = await wait_for_terminal(client, accepted.json()["id"])
    assert run["status"] == "failed"
    assert run["error"] == "Calculator tool is not enabled for this agent."
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    assert [event["type"] for event in events] == ["run.started", "run.failed"]
