from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domain.contracts import AgentCreate, AgentEvent, RunStatus
from app.main import create_app
from app.observability.redaction import REDACTED, redact_text, redact_value
from app.persistence.database import settings
from app.persistence.models import RunEventModel, RunModel
from app.runtime.providers import MockProvider


async def _create_agent(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": "Observable Calculator",
            "instructions": "Use the calculator.",
            "runtime_mode": "mock",
            "tools": ["calculator"],
        },
    )
    assert response.status_code == 201
    return response.json()


async def _terminal_run(
    client: AsyncClient, agent_id: object, user_input: str
) -> dict[str, object]:
    accepted = await client.post(f"/agents/{agent_id}/runs", json={"input": user_input})
    assert accepted.status_code == 202
    for _ in range(100):
        run = (await client.get(f"/runs/{accepted.json()['id']}")).json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("run did not terminate")


@pytest.mark.asyncio
async def test_completed_calculator_observability_is_correlated_and_real(
    client: AsyncClient,
) -> None:
    agent = await _create_agent(client)
    run = await _terminal_run(client, agent["id"], "Calculate 128 * 37 + 456")
    assert run["output"] == "5192"

    events = (await client.get(f"/runs/{run['id']}/events")).json()
    response = await client.get(f"/runs/{run['id']}/observability")
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["status"] == "completed"
    assert metrics["termination_reason"] == "completed"
    assert metrics["runtime_type"] == metrics["provider_type"] == "mock"
    assert metrics["duration_ms"] >= 0
    assert metrics["step_count"] == 2
    assert metrics["event_count"] == len(events)
    assert metrics["tool_calls"] == {"total": 1, "succeeded": 1, "failed": 0}
    assert metrics["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert metrics["started_at"] is not None
    assert metrics["terminal_at"] is not None

    tool_events = [event for event in events if event["type"].startswith("tool.")]
    assert [event["type"] for event in tool_events] == [
        "tool.selected",
        "tool.started",
        "tool.completed",
    ]
    assert len({event["tool_call_id"] for event in tool_events}) == 1
    assert {event["step_index"] for event in tool_events} == {1}
    tool = metrics["tools"][0]
    assert tool["tool_name"] == "calculator"
    assert tool["status"] == "completed"
    assert tool["duration_ms"] >= 0
    assert tool["output"] == {"result": "5192"}


@pytest.mark.asyncio
async def test_failed_tool_and_dashboard_statuses_are_not_fabricated(
    client: AsyncClient,
) -> None:
    agent = await _create_agent(client)
    run = await _terminal_run(client, agent["id"], "Calculate 1 / 0")
    metrics = (await client.get(f"/runs/{run['id']}/observability")).json()
    assert metrics["status"] == "failed"
    assert metrics["termination_reason"] == "tool_error"
    assert metrics["error_category"] == "tool_error"
    assert metrics["tool_calls"] == {"total": 1, "succeeded": 0, "failed": 1}
    assert "Division by zero" in metrics["error_summary"]
    assert "Traceback" not in metrics["error_summary"]

    dashboard = (await client.get("/observability/dashboard")).json()
    assert dashboard["total_runs"] == 1
    assert dashboard["failed"] == 1
    assert dashboard["cancelled"] == 0
    assert dashboard["success_rate"] == 0
    assert dashboard["average_duration_ms"] >= 0


@pytest.mark.asyncio
async def test_cancelled_run_observability_is_not_failed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def block(self: MockProvider, context: object) -> object:
        del self, context
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(MockProvider, "decide", block)
    agent = await _create_agent(client)
    accepted = await client.post(
        f"/agents/{agent['id']}/runs", json={"input": "Calculate 1 + 1"}
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert (await client.post(f"/runs/{accepted.json()['id']}/cancel")).status_code == 202
    for _ in range(100):
        metrics = (await client.get(f"/runs/{accepted.json()['id']}/observability")).json()
        if metrics["status"] == "cancelled":
            break
        await asyncio.sleep(0.01)
    assert metrics["status"] == "cancelled"
    assert metrics["termination_reason"] == "cancelled"
    assert metrics["error_category"] == "cancelled"
    assert metrics["duration_ms"] >= 0
    dashboard = (await client.get("/observability/dashboard")).json()
    assert dashboard["cancelled"] == 1
    assert dashboard["failed"] == 0


@pytest.mark.asyncio
async def test_trace_redaction_precedes_database_and_api_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'redaction.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        repositories = app.state.agent_service._repositories
        agent = await repositories.create_agent(
            AgentCreate(name="Redaction Agent", instructions="Protect secrets.", tools=[])
        )
        run = await repositories.create_run(agent.id, "redact")
        await repositories.update_run(run.id, RunStatus.RUNNING)
        await repositories.append_event(
            AgentEvent(
                run_id=run.id,
                sequence=1,
                type="tool.started",
                tool_call_id=UUID(int=7),
                step_index=1,
                payload={
                    "tool": "fixture",
                    "arguments": {
                        "authorization": "Bearer super-secret",
                        "nested": {"api_key": "secret-key"},
                        "items": [{"password": "fake-api-key"}],
                    },
                },
            )
        )
        await repositories.append_event(
            AgentEvent(
                run_id=run.id,
                sequence=2,
                type="tool.completed",
                tool_call_id=UUID(int=7),
                step_index=1,
                payload={
                    "tool": "fixture",
                    "result": {
                        "access_token": "output-secret",
                        "records": [{"set-cookie": "session=private-cookie"}],
                    },
                },
            )
        )
        await repositories.finish_run(
            run.id,
            RunStatus.FAILED,
            AgentEvent(
                run_id=run.id,
                sequence=3,
                type="run.failed",
                payload={
                    "error": "authorization: Basic super-secret",
                    "error_category": "fixture_error",
                },
            ),
            error="authorization: Bearer persisted-run-secret",
        )
        async with repositories._sessions() as session:
            raw_rows = list(
                await session.scalars(
                    select(RunEventModel.payload_json).where(
                        RunEventModel.run_id == str(run.id)
                    )
                )
            )
            raw_run_error = await session.scalar(
                select(RunModel.error).where(RunModel.id == str(run.id))
            )
        raw = "\n".join(raw_rows)
        assert "Basic super-secret" not in raw
        assert "super-secret" not in raw
        assert "secret-key" not in raw
        assert "fake-api-key" not in raw
        assert "output-secret" not in raw
        assert "private-cookie" not in raw
        assert _redacted_count(raw) >= 6
        assert raw_run_error == "authorization:[REDACTED]"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.get(f"/runs/{run.id}/events")
            serialized = json.dumps(response.json())
            assert "super-secret" not in serialized
            assert "secret-key" not in serialized
            assert "fake-api-key" not in serialized
            assert "output-secret" not in serialized
            assert "private-cookie" not in serialized
            assert "[REDACTED]" in serialized
            run_response = await http.get(f"/runs/{run.id}")
            assert run_response.json()["error"] == "authorization:[REDACTED]"
            stream = await http.get(f"/runs/{run.id}/stream")
            assert "super-secret" not in stream.text
            assert "output-secret" not in stream.text
            assert "private-cookie" not in stream.text
            assert "[REDACTED]" in stream.text


def _redacted_count(value: str) -> int:
    return value.count("[REDACTED]")


def test_redaction_handles_key_variants_auth_schemes_and_openai_shaped_keys() -> None:
    structured = redact_value(
        {
            "AUTHORIZATION": "Bearer abc",
            "apiKey": "one",
            "API_KEY": "two",
            "access_token": "three",
            "refresh-token": "four",
            "Password": "five",
            "secret": "six",
            "Cookie": "seven",
            "set-cookie": "eight",
            "nested": [{"authorization": "Basic abc"}],
        }
    )
    assert isinstance(structured, dict)
    assert structured["AUTHORIZATION"] == REDACTED
    assert structured["apiKey"] == REDACTED
    assert structured["API_KEY"] == REDACTED
    assert structured["nested"] == [{"authorization": REDACTED}]

    free_text = redact_text(
        "Bearer abc Basic ZGVtbzpwYXNz sk-test-super-secret; ordinary token prose"
    )
    assert "Bearer abc" not in free_text
    assert "Basic ZGVtbzpwYXNz" not in free_text
    assert "sk-test-super-secret" not in free_text
    assert "ordinary token prose" in free_text


def test_sse_event_type_rejects_stream_framing_characters() -> None:
    with pytest.raises(ValueError):
        AgentEvent(
            run_id=UUID(int=1),
            sequence=1,
            type="safe\nevent: forged",
            payload={"data": "still data"},
        )


def test_event_payload_has_a_persistence_size_bound() -> None:
    with pytest.raises(ValueError, match="payload exceeds"):
        AgentEvent(
            run_id=UUID(int=1),
            sequence=1,
            type="policy.checked",
            payload={"value": "x" * 300_000},
        )


@pytest.mark.asyncio
async def test_legacy_payload_only_event_remains_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        repositories = app.state.agent_service._repositories
        agent = await repositories.create_agent(
            AgentCreate(name="Legacy Event Agent", instructions="Test.", tools=[])
        )
        run = await repositories.create_run(agent.id, "legacy event")
        async with repositories._sessions() as session:
            session.add(
                RunEventModel(
                    event_id="00000000-0000-0000-0000-000000000099",
                    run_id=str(run.id),
                    sequence=99,
                    type="legacy.event",
                    timestamp=datetime(2026, 8, 20, tzinfo=UTC),
                    payload_json=json.dumps({"legacy": True}),
                )
            )
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            events = (await http.get(f"/runs/{run.id}/events")).json()
            legacy = next(event for event in events if event["type"] == "legacy.event")
            assert legacy["payload"] == {"legacy": True}
            assert legacy["step_index"] is None
            assert legacy["tool_call_id"] is None


@pytest.mark.asyncio
async def test_unknown_event_survives_persistence_and_generic_sse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'unknown.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        repositories = app.state.agent_service._repositories
        agent = await repositories.create_agent(
            AgentCreate(name="Future Event Agent", instructions="Test.", tools=[])
        )
        run = await repositories.create_run(agent.id, "future")
        await repositories.update_run(run.id, RunStatus.RUNNING)
        timestamp = datetime(2026, 8, 20, tzinfo=UTC)
        await repositories.append_event(
            AgentEvent(
                run_id=run.id,
                sequence=1,
                type="policy.checked",
                timestamp=timestamp,
                payload={"policy": "safe"},
            )
        )
        await repositories.finish_run(
            run.id,
            RunStatus.COMPLETED,
            AgentEvent(
                run_id=run.id,
                sequence=2,
                type="run.completed",
                timestamp=timestamp + timedelta(milliseconds=250),
                duration_ms=250,
                payload={"termination_reason": "completed", "steps": 0},
            ),
            output="done",
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            events = (await http.get(f"/runs/{run.id}/events")).json()
            assert events[0]["type"] == "policy.checked"
            stream = await http.get(f"/runs/{run.id}/stream")
            assert "event: policy.checked" in stream.text
            assert stream.text.count("event: agent.event") == 2
