from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.contracts import (
    AgentCreate,
    AgentEvent,
    AgentRun,
    CancellationToken,
    EventSink,
    RunStatus,
    RuntimeInput,
    RuntimeMode,
)
from app.main import create_app
from app.memory.contracts import MemoryKind, MemoryRecord
from app.memory.policy import MemoryPolicy
from app.memory.store import SqlAlchemyMemoryStore
from app.persistence.database import build_database, settings
from app.persistence.models import AgentModel, Base
from app.persistence.repositories import Repositories, _agent_row_statement
from app.runtime.mock import MockRuntime


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


class FinalizationPausingRuntime:
    def __init__(self, delegate: MockRuntime) -> None:
        self._delegate = delegate
        self.ready_to_finalize = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def is_configured(self) -> bool:
        return True

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun:
        result = await self._delegate.run(runtime_input, emit, cancellation)
        self.ready_to_finalize.set()
        await self.release.wait()
        return result


class ConcurrentFinalizationRuntime:
    def __init__(self, delegate: MockRuntime, expected_runs: int = 2) -> None:
        self._delegate = delegate
        self._expected_runs = expected_runs
        self._ready_count = 0
        self._guard = asyncio.Lock()
        self.all_ready = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def is_configured(self) -> bool:
        return True

    async def run(
        self,
        runtime_input: RuntimeInput,
        emit: EventSink,
        cancellation: CancellationToken | None = None,
    ) -> AgentRun:
        result = await self._delegate.run(runtime_input, emit, cancellation)
        async with self._guard:
            self._ready_count += 1
            if self._ready_count == self._expected_runs:
                self.all_ready.set()
        await self.release.wait()
        return result


@pytest.mark.asyncio
async def test_second_run_retrieves_fact_for_same_agent(client: AsyncClient) -> None:
    agent = await create_agent(client, "Memory Agent")

    first = await run_to_completion(client, agent["id"], "Remember that project codename is Atlas.")
    assert first["status"] == "completed"
    assert "memory.written" in await event_types(client, first["id"])
    first_events = (await client.get(f"/runs/{first['id']}/events")).json()
    written = next(event for event in first_events if event["type"] == "memory.written")
    assert written["payload"]["write_result"] == "created"

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
    assert retrieval["duration_ms"] >= 0
    observability = (await client.get(f"/runs/{second['id']}/observability")).json()
    assert observability["event_statistics"]["memory.retrieved"] == 1


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
    assert deleted.content == b""
    assert "content-type" not in deleted.headers
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
async def test_disable_wins_serialization_before_run_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'disable-race.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        service = app.state.agent_service
        original_runtime = service._runtimes[RuntimeMode.MOCK]
        assert isinstance(original_runtime, MockRuntime)
        runtime = FinalizationPausingRuntime(original_runtime)
        service._runtimes[RuntimeMode.MOCK] = runtime
        repositories = service._repositories
        original_acquire = repositories._acquire_agent_memory_ownership
        disable_has_ownership = asyncio.Event()
        allow_disable_commit = asyncio.Event()
        finalization_attempted = asyncio.Event()
        finalization_has_ownership = asyncio.Event()

        async def coordinate_ownership(
            session: AsyncSession, agent_id: UUID
        ) -> AgentModel:
            task = asyncio.current_task()
            is_disable = task is not None and task.get_name() == "memory-disable"
            if not is_disable:
                finalization_attempted.set()
            agent = await original_acquire(session, agent_id)
            if is_disable:
                disable_has_ownership.set()
                await allow_disable_commit.wait()
            else:
                finalization_has_ownership.set()
            return agent

        monkeypatch.setattr(
            repositories, "_acquire_agent_memory_ownership", coordinate_ownership
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            agent = await create_agent(http, "Disable Race Agent")
            accepted = await http.post(
                f"/agents/{agent['id']}/runs",
                json={"input": "Remember that project codename is Atlas."},
            )
            assert accepted.status_code == 202
            await asyncio.wait_for(runtime.ready_to_finalize.wait(), timeout=2)
            disable_task = asyncio.create_task(
                http.patch(
                    f"/agents/{agent['id']}/memory-settings", json={"enabled": False}
                ),
                name="memory-disable",
            )
            await asyncio.wait_for(disable_has_ownership.wait(), timeout=2)
            runtime.release.set()
            await asyncio.wait_for(finalization_attempted.wait(), timeout=2)
            await asyncio.sleep(0.05)
            assert not finalization_has_ownership.is_set()

            allow_disable_commit.set()
            disabled = await asyncio.wait_for(disable_task, timeout=2)
            assert disabled.status_code == 200
            await asyncio.wait_for(finalization_has_ownership.wait(), timeout=2)
            run = await run_result(http, accepted.json()["id"])

            assert run["status"] == "completed"
            assert (await http.get(f"/agents/{agent['id']}/memories")).json() == []
            assert "memory.written" not in await event_types(http, run["id"])


@pytest.mark.asyncio
async def test_finalization_wins_then_disable_blocks_future_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'finalization-wins.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        service = app.state.agent_service
        original_runtime = service._runtimes[RuntimeMode.MOCK]
        assert isinstance(original_runtime, MockRuntime)
        runtime = FinalizationPausingRuntime(original_runtime)
        service._runtimes[RuntimeMode.MOCK] = runtime
        repositories = service._repositories
        original_acquire = repositories._acquire_agent_memory_ownership
        finalization_has_ownership = asyncio.Event()
        allow_finalization_commit = asyncio.Event()
        disable_attempted = asyncio.Event()
        disable_has_ownership = asyncio.Event()

        async def coordinate_ownership(
            session: AsyncSession, agent_id: UUID
        ) -> AgentModel:
            task = asyncio.current_task()
            is_disable = task is not None and task.get_name() == "memory-disable"
            if is_disable:
                disable_attempted.set()
            agent = await original_acquire(session, agent_id)
            if is_disable:
                disable_has_ownership.set()
            else:
                finalization_has_ownership.set()
                await allow_finalization_commit.wait()
            return agent

        monkeypatch.setattr(
            repositories, "_acquire_agent_memory_ownership", coordinate_ownership
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            agent = await create_agent(http, "Finalization Race Agent")
            accepted = await http.post(
                f"/agents/{agent['id']}/runs",
                json={"input": "Remember that project codename is Atlas."},
            )
            assert accepted.status_code == 202
            await asyncio.wait_for(runtime.ready_to_finalize.wait(), timeout=2)
            runtime.release.set()
            await asyncio.wait_for(finalization_has_ownership.wait(), timeout=2)

            disable_task = asyncio.create_task(
                http.patch(
                    f"/agents/{agent['id']}/memory-settings", json={"enabled": False}
                ),
                name="memory-disable",
            )
            await asyncio.wait_for(disable_attempted.wait(), timeout=2)
            await asyncio.sleep(0.05)
            assert not disable_has_ownership.is_set()

            allow_finalization_commit.set()
            run = await run_result(http, accepted.json()["id"])
            disabled = await asyncio.wait_for(disable_task, timeout=2)
            assert disabled.status_code == 200
            assert disabled.json()["enabled"] is False
            assert run["status"] == "completed"
            assert len((await http.get(f"/agents/{agent['id']}/memories")).json()) == 1
            assert (await event_types(http, run["id"]))[-2:] == [
                "memory.written",
                "run.completed",
            ]

            later = await run_to_completion(
                http, agent["id"], "Remember that deployment region is west."
            )
            assert later["status"] == "completed"
            assert "memory.written" not in await event_types(http, later["id"])
            assert len((await http.get(f"/agents/{agent['id']}/memories")).json()) == 1


@pytest.mark.asyncio
async def test_enabled_memory_and_terminal_state_commit_together(client: AsyncClient) -> None:
    agent = await create_agent(client, "Atomic Success Agent")
    run = await run_to_completion(
        client, agent["id"], "Remember that project codename is Atlas."
    )

    assert run["status"] == "completed"
    assert len((await client.get(f"/agents/{agent['id']}/memories")).json()) == 1
    assert (await event_types(client, run["id"]))[-2:] == [
        "memory.written",
        "run.completed",
    ]
    events = (await client.get(f"/runs/{run['id']}/events")).json()
    written, completed = events[-2:]
    assert datetime.fromisoformat(written["timestamp"]) <= datetime.fromisoformat(
        completed["timestamp"]
    )
    assert completed["duration_ms"] >= 0


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


@pytest.mark.asyncio
async def test_terminal_event_failure_rolls_back_memory_and_run_completion(
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'atomic-rollback.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repositories = Repositories(sessions)
    store = SqlAlchemyMemoryStore(sessions)
    agent = await repositories.create_agent(
        AgentCreate(name="Rollback Agent", instructions="Remember facts.", tools=[])
    )
    run = await repositories.create_run(agent.id, "Remember that project codename is Atlas.")
    await repositories.update_run(run.id, RunStatus.RUNNING)
    existing_event = AgentEvent(run_id=run.id, sequence=1, type="run.started")
    await repositories.append_event(existing_event)
    candidate = MemoryPolicy().propose_write(
        agent_id=agent.id,
        run_id=run.id,
        user_input=run.input,
        now=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert candidate is not None

    with pytest.raises(IntegrityError):
        await repositories.finish_completed_run_with_memory(
            run.id,
            agent.id,
            AgentEvent(
                event_id=existing_event.event_id,
                run_id=run.id,
                sequence=2,
                type="run.completed",
            ),
            output="done",
            candidate=candidate,
        )

    assert await store.list(agent.id) == []
    assert (await repositories.get_run(run.id)).status == RunStatus.RUNNING
    assert [event.type for event in await repositories.list_events(run.id)] == ["run.started"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_duplicate_writes_upsert_one_agent_scoped_memory(
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'memory-dedupe.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store = SqlAlchemyMemoryStore(sessions)
    agent_id = uuid4()
    created_at = datetime(2026, 8, 1, tzinfo=UTC)
    contents = ["Project   Codename is Ａtlas", "project codename is Atlas"]
    records = [
        MemoryRecord(
            id=UUID(int=index + 1),
            agent_id=agent_id,
            kind=MemoryKind.LONG_TERM,
            content=contents[index],
            importance=0.9,
            created_at=created_at,
            expires_at=created_at + timedelta(days=180),
        )
        for index in range(2)
    ]

    stored = await asyncio.gather(*(store.write(record) for record in records))

    memories = await store.list(agent_id)
    assert len(memories) == 1
    assert stored[0].id == stored[1].id == memories[0].id
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_concurrent_runs_dedupe_through_complete_application_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'concurrent-runs.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        service = app.state.agent_service
        original_runtime = service._runtimes[RuntimeMode.MOCK]
        assert isinstance(original_runtime, MockRuntime)
        runtime = ConcurrentFinalizationRuntime(original_runtime)
        service._runtimes[RuntimeMode.MOCK] = runtime
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            agent = await create_agent(http, "Concurrent Run Agent")
            requests = [
                http.post(
                    f"/agents/{agent['id']}/runs",
                    json={"input": "Remember that project codename is Atlas."},
                )
                for _ in range(2)
            ]
            accepted = await asyncio.gather(*requests)
            assert [response.status_code for response in accepted] == [202, 202]
            await asyncio.wait_for(runtime.all_ready.wait(), timeout=2)
            runtime.release.set()

            runs = await asyncio.gather(
                *(run_result(http, response.json()["id"]) for response in accepted)
            )
            assert [run["status"] for run in runs] == ["completed", "completed"]
            assert [run["error"] for run in runs] == [None, None]
            memories = (await http.get(f"/agents/{agent['id']}/memories")).json()
            assert len(memories) == 1
            assert memories[0]["content"] == "project codename is Atlas"
            written_memory_ids: list[str] = []
            for run in runs:
                events = (await http.get(f"/runs/{run['id']}/events")).json()
                assert [event["type"] for event in events][-2:] == [
                    "memory.written",
                    "run.completed",
                ]
                written_memory_ids.append(events[-2]["payload"]["memory_id"])
            assert written_memory_ids == [memories[0]["id"], memories[0]["id"]]


def test_postgresql_agent_memory_ownership_uses_row_lock() -> None:
    statement = _agent_row_statement(UUID(int=1), for_update=True)
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert compiled.rstrip().endswith("FOR UPDATE")


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


def test_ranking_components_threshold_ties_limits_and_context_budget() -> None:
    now = datetime(2026, 1, 31, tzinfo=UTC)
    agent_id = UUID(int=100)

    def record(
        identifier: int,
        content: str,
        *,
        importance: float = 0.5,
        age_days: int = 0,
    ) -> MemoryRecord:
        return MemoryRecord(
            id=UUID(int=identifier),
            agent_id=agent_id,
            kind=MemoryKind.LONG_TERM,
            content=content,
            importance=importance,
            created_at=now - timedelta(days=age_days),
            expires_at=now + timedelta(days=180),
        )

    relevance = MemoryPolicy().rank(
        "alpha beta gamma delta",
        [record(1, "alpha beta gamma"), record(2, "alpha unrelated words")],
        now=now,
    )
    assert [match.record.id for match in relevance] == [UUID(int=1), UUID(int=2)]

    importance = MemoryPolicy().rank(
        "alpha",
        [record(1, "alpha", importance=0.2), record(2, "alpha", importance=0.9)],
        now=now,
    )
    assert importance[0].record.id == UUID(int=2)

    recency = MemoryPolicy().rank(
        "alpha",
        [record(1, "alpha", age_days=30), record(2, "alpha", age_days=0)],
        now=now,
    )
    assert recency[0].record.id == UUID(int=2)

    threshold = MemoryPolicy().rank(
        "alpha beta gamma delta",
        [record(1, "alpha one two three"), record(2, "alpha one two three four")],
        now=now,
    )
    assert [match.record.id for match in threshold] == [UUID(int=1)]
    assert threshold[0].relevance == 0.25

    ties = MemoryPolicy().rank(
        "alpha", [record(1, "alpha"), record(2, "alpha")], now=now
    )
    assert [match.record.id for match in ties] == [UUID(int=2), UUID(int=1)]

    limited = MemoryPolicy(max_results=2).rank(
        "alpha", [record(index, "alpha") for index in range(1, 5)], now=now
    )
    assert len(limited) == 2

    oversized = "alpha " + ("x" * 1495)
    budgeted = MemoryPolicy(max_context_chars=1_500).rank(
        "alpha",
        [
            record(2, oversized, importance=1),
            record(1, "alpha", importance=0.5),
        ],
        now=now,
    )
    assert [match.record.id for match in budgeted] == [UUID(int=1)]
    assert len(oversized) == 1_501
    assert sum(len(match.record.content) for match in budgeted) <= 1_500


async def run_result(client: AsyncClient, run_id: object) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("run did not reach a terminal status")
