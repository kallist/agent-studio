from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.memory.contracts import MemoryKind, MemoryRecord
from app.memory.policy import MemoryPolicy
from app.memory.store import SqlAlchemyMemoryStore
from app.persistence.database import build_database
from app.persistence.models import Base


async def create_agent(client: AsyncClient, name: str) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "instructions": "Answer from relevant memory when it is available.",
            "runtime_mode": "mock",
            "tools": [],
        },
    )
    assert response.status_code == 201
    return response.json()


async def run_to_completion(
    client: AsyncClient, agent_id: object, user_input: str
) -> dict[str, object]:
    accepted = await client.post(
        f"/agents/{agent_id}/runs",
        json={"input": user_input},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["id"]
    for _ in range(100):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("run did not reach a terminal status")


async def event_types(client: AsyncClient, run_id: object) -> list[str]:
    response = await client.get(f"/runs/{run_id}/events")
    assert response.status_code == 200
    return [event["type"] for event in response.json()]


@pytest.mark.asyncio
async def test_second_run_retrieves_fact_for_same_agent(client: AsyncClient) -> None:
    agent = await create_agent(client, "Memory Agent")

    first = await run_to_completion(client, agent["id"], "Remember that project codename is Atlas.")
    assert first["status"] == "completed"
    assert "memory.written" in await event_types(client, first["id"])

    memories = (await client.get(f"/agents/{agent['id']}/memories")).json()
    assert [memory["content"] for memory in memories] == ["project codename is Atlas"]

    second = await run_to_completion(client, agent["id"], "What is the project codename?")
    assert second["status"] == "completed"
    assert "Atlas" in str(second["output"])
    response = await client.get(f"/runs/{second['id']}/events")
    retrieval = next(event for event in response.json() if event["type"] == "memory.retrieved")
    match = retrieval["payload"]["matches"][0]
    assert match["score"] > 0
    assert match["relevance"] > 0
    assert match["recency"] > 0
    assert match["importance"] == 0.9


@pytest.mark.asyncio
async def test_unrelated_memory_does_not_enter_runtime_context(client: AsyncClient) -> None:
    agent = await create_agent(client, "Relevance Agent")
    await run_to_completion(client, agent["id"], "Remember that favorite color is blue.")

    run = await run_to_completion(client, agent["id"], "What is the project deadline?")
    assert "blue" not in str(run["output"]).lower()
    assert "memory.retrieved" not in await event_types(client, run["id"])


@pytest.mark.asyncio
async def test_deleted_memory_is_not_retrieved(client: AsyncClient) -> None:
    agent = await create_agent(client, "Deletion Agent")
    await run_to_completion(client, agent["id"], "Remember that project codename is Atlas.")
    memories = (await client.get(f"/agents/{agent['id']}/memories")).json()

    deleted = await client.delete(f"/agents/{agent['id']}/memories/{memories[0]['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/agents/{agent['id']}/memories")).json() == []

    run = await run_to_completion(client, agent["id"], "What is the project codename?")
    assert "Atlas" not in str(run["output"])
    assert "memory.retrieved" not in await event_types(client, run["id"])


@pytest.mark.asyncio
async def test_memory_disabled_prevents_writes(client: AsyncClient) -> None:
    agent = await create_agent(client, "Disabled Agent")
    setting = await client.patch(
        f"/agents/{agent['id']}/memory-settings",
        json={"enabled": False},
    )
    assert setting.status_code == 200
    assert setting.json()["enabled"] is False

    run = await run_to_completion(client, agent["id"], "Remember that project codename is Atlas.")
    assert "memory.written" not in await event_types(client, run["id"])
    assert (await client.get(f"/agents/{agent['id']}/memories")).json() == []


@pytest.mark.asyncio
async def test_memory_is_isolated_between_agents(client: AsyncClient) -> None:
    first_agent = await create_agent(client, "First Agent")
    second_agent = await create_agent(client, "Second Agent")
    await run_to_completion(client, first_agent["id"], "Remember that project codename is Atlas.")
    first_memories = (await client.get(f"/agents/{first_agent['id']}/memories")).json()

    cross_agent_delete = await client.delete(
        f"/agents/{second_agent['id']}/memories/{first_memories[0]['id']}"
    )
    assert cross_agent_delete.status_code == 404

    run = await run_to_completion(client, second_agent["id"], "What is the project codename?")
    assert "Atlas" not in str(run["output"])
    assert "memory.retrieved" not in await event_types(client, run["id"])
    assert (await client.get(f"/agents/{second_agent['id']}/memories")).json() == []
    assert len((await client.get(f"/agents/{first_agent['id']}/memories")).json()) == 1


@pytest.mark.asyncio
async def test_expired_memory_is_physically_purged(tmp_path: Path) -> None:
    database_path = (tmp_path / "memory-expiration.db").as_posix()
    engine, sessions = build_database(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = SqlAlchemyMemoryStore(sessions)
    agent_id = uuid4()
    now = datetime.now(UTC)
    expired = MemoryRecord(
        agent_id=agent_id,
        kind=MemoryKind.LONG_TERM,
        content="project codename is Atlas",
        importance=0.9,
        created_at=now - timedelta(days=181),
        expires_at=now - timedelta(days=1),
    )
    await store.write(expired)

    assert await store.list(agent_id) == []
    assert await store.purge_expired(now) == 0
    await engine.dispose()


def test_policy_excludes_expired_unrelated_and_sensitive_records() -> None:
    policy = MemoryPolicy()
    now = datetime.now(UTC)
    expired = MemoryRecord(
        agent_id=uuid4(),
        kind=MemoryKind.LONG_TERM,
        content="project codename is Atlas",
        importance=1,
        created_at=now - timedelta(days=200),
        expires_at=now - timedelta(seconds=1),
    )

    assert policy.rank("What is the project codename?", [expired], now=now) == []
    assert (
        policy.propose_write(
            agent_id=uuid4(),
            run_id=uuid4(),
            user_input="This was a normal transient conversation.",
            now=now,
        )
        is None
    )
    assert (
        policy.propose_write(
            agent_id=uuid4(),
            run_id=uuid4(),
            user_input="Remember that my password is swordfish.",
            now=now,
        )
        is None
    )
