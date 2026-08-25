from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.service import EventBroker
from app.domain.contracts import AgentEvent
from app.main import create_app
from app.persistence.database import build_database, settings
from app.persistence.models import RunModel

pytestmark = [pytest.mark.reliability, pytest.mark.asyncio]

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


async def _wait_for_terminal(client: AsyncClient, run_id: str) -> dict[str, object]:
    async with asyncio.timeout(5):
        while True:
            response = await client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            run = response.json()
            if run["status"] in TERMINAL_STATUSES:
                return run
            await asyncio.sleep(0.01)


async def _wait_for_status(
    client: AsyncClient, run_id: str, expected: str
) -> dict[str, object]:
    async with asyncio.timeout(5):
        while True:
            response = await client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            run = response.json()
            if run["status"] == expected:
                return run
            await asyncio.sleep(0.01)


async def test_concurrent_calculator_runs_are_unique_ordered_and_terminal(
    client: AsyncClient,
) -> None:
    agent_response = await client.post(
        "/agents",
        json={
            "name": "Reliability Calculator",
            "instructions": "Use the calculator.",
            "runtime_mode": "mock",
            "tools": ["calculator"],
        },
    )
    assert agent_response.status_code == 201
    agent_id = agent_response.json()["id"]

    accepted = await asyncio.gather(
        *[
            client.post(
                f"/agents/{agent_id}/runs",
                json={"input": "Calculate 128 * 37 + 456"},
            )
            for _ in range(12)
        ]
    )
    assert all(response.status_code == 202 for response in accepted)
    run_ids = [response.json()["id"] for response in accepted]
    assert len(set(run_ids)) == len(run_ids)

    runs = await asyncio.gather(
        *[_wait_for_terminal(client, run_id) for run_id in run_ids]
    )
    assert all(run["status"] == "completed" for run in runs)
    assert all(run["output"] == "5192" for run in runs)

    event_responses = await asyncio.gather(
        *[client.get(f"/runs/{run_id}/events") for run_id in run_ids]
    )
    for response in event_responses:
        assert response.status_code == 200
        events = response.json()
        sequences = [event["sequence"] for event in events]
        assert sequences == list(range(1, len(events) + 1))
        terminal = [
            event
            for event in events
            if event["type"] in {"run.completed", "run.failed", "run.cancelled"}
        ]
        assert [event["type"] for event in terminal] == ["run.completed"]


async def test_event_broker_queue_is_bounded() -> None:
    broker = EventBroker()
    run_id = uuid4()
    queue = broker.subscribe(run_id)

    for sequence in range(1, EventBroker._QUEUE_SIZE * 2 + 1):
        await broker.publish(
            AgentEvent(
                run_id=run_id,
                sequence=sequence,
                type="step.completed",
                payload={"sequence": sequence},
            )
        )

    assert queue.maxsize == EventBroker._QUEUE_SIZE
    assert queue.qsize() == EventBroker._QUEUE_SIZE
    broker.unsubscribe(run_id, queue)
    assert run_id not in broker._subscribers


async def test_sse_stream_disconnect_releases_subscriber_and_run_remains_manageable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocking_input = "__task13_sse_disconnect_block__"
    monkeypatch.setattr(settings, "mock_provider_block_input", blocking_input)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'sse.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            agent = (
                await client.post(
                    "/agents",
                    json={
                        "name": "SSE Disconnect Agent",
                        "instructions": "Wait deterministically.",
                        "runtime_mode": "mock",
                        "tools": [],
                    },
                )
            ).json()
            accepted = await client.post(
                f"/agents/{agent['id']}/runs", json={"input": blocking_input}
            )
            run_id = UUID(accepted.json()["id"])
            run = await _wait_for_status(client, str(run_id), "running")
            assert run["status"] == "running"

            service = app.state.agent_service
            stream = service.stream_events(run_id)
            first_event = await anext(stream)
            assert first_event.type == "run.started"
            assert len(service._broker._subscribers[run_id]) == 1
            await stream.aclose()
            assert run_id not in service._broker._subscribers

            still_running = (await client.get(f"/runs/{run_id}")).json()
            assert still_running["status"] == "running"
            assert (await client.post(f"/runs/{run_id}/cancel")).status_code == 202
            terminal = await _wait_for_terminal(client, str(run_id))
            assert terminal["status"] == "cancelled"


async def test_startup_recovers_abandoned_normal_run_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'restart.db').as_posix()}"
    knowledge_path = str(tmp_path / "knowledge")
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    first_app = create_app(database_url, knowledge_path)
    async with first_app.router.lifespan_context(first_app):
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as client:
            agent_response = await client.post(
                "/agents",
                json={
                    "name": "Restart Agent",
                    "instructions": "Answer deterministically.",
                    "runtime_mode": "mock",
                    "tools": [],
                },
            )
            assert agent_response.status_code == 201
            agent_id = agent_response.json()["id"]

    run_id = uuid4()
    engine, sessions = build_database(database_url)
    async with sessions() as session:
        session.add(
            RunModel(
                id=str(run_id),
                agent_id=agent_id,
                status="running",
                run_kind="normal",
                input="interrupted",
            )
        )
        await session.commit()
    await engine.dispose()

    restarted_app = create_app(database_url, knowledge_path)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://test"
        ) as client:
            run_response = await client.get(f"/runs/{run_id}")
            assert run_response.status_code == 200
            assert run_response.json()["status"] == "failed"
            events = (await client.get(f"/runs/{run_id}/events")).json()
            assert [event["type"] for event in events] == ["run.failed"]
            assert events[0]["payload"]["error_category"] == "process_restart"
            observability = (await client.get(f"/runs/{run_id}/observability")).json()
            assert observability["error_category"] == "process_restart"
            assert observability["termination_reason"] == "process_restart"


async def test_graceful_shutdown_terminates_owned_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'shutdown.db').as_posix()}"
    blocking_input = "__task13_shutdown_block__"
    monkeypatch.setattr(settings, "mock_provider_block_input", blocking_input)
    app = create_app(database_url, str(tmp_path / "knowledge"))
    run_id: UUID

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            agent = (
                await client.post(
                    "/agents",
                    json={
                        "name": "Shutdown Agent",
                        "instructions": "Wait deterministically.",
                        "runtime_mode": "mock",
                        "tools": [],
                    },
                )
            ).json()
            accepted = await client.post(
                f"/agents/{agent['id']}/runs", json={"input": blocking_input}
            )
            assert accepted.status_code == 202
            run_id = UUID(accepted.json()["id"])
            async with asyncio.timeout(2):
                for _ in range(200):
                    if (await client.get(f"/runs/{run_id}")).json()["status"] == "running":
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("run did not enter running state before shutdown")

    restarted_app = create_app(database_url, str(tmp_path / "knowledge"))
    async with restarted_app.router.lifespan_context(restarted_app):
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://test"
        ) as client:
            run = (await client.get(f"/runs/{run_id}")).json()
            assert run["status"] in {"cancelled", "failed"}
            events = (await client.get(f"/runs/{run_id}/events")).json()
            terminal_events = [
                event
                for event in events
                if event["type"] in {"run.completed", "run.failed", "run.cancelled"}
            ]
            assert len(terminal_events) == 1
