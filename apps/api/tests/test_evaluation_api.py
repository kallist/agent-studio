from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.contracts import AgentDecision, RunKind, RunStatus
from app.main import create_app
from app.persistence.database import settings
from app.runtime.providers import MockProvider


async def _agent(
    client: AsyncClient,
    *,
    name: str = "Evaluation Agent",
    tools: list[str] | None = None,
    knowledge_base_ids: list[str] | None = None,
    memory_enabled: bool = True,
) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "instructions": "Use the configured tools and answer deterministically.",
            "runtime_mode": "mock",
            "tools": ["calculator"] if tools is None else tools,
            "knowledge_base_ids": knowledge_base_ids or [],
            "memory_enabled": memory_enabled,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wait_evaluation(client: AsyncClient, evaluation_run_id: str) -> dict[str, object]:
    for _ in range(200):
        response = await client.get(f"/evaluation-runs/{evaluation_run_id}")
        assert response.status_code == 200
        evaluation = response.json()
        if evaluation["status"] in {"completed", "failed", "cancelled"}:
            return evaluation
        await asyncio.sleep(0.01)
    pytest.fail("evaluation did not reach a terminal status")


@pytest.mark.asyncio
async def test_calculator_and_intentional_failure_use_real_runs_and_isolate_dashboard(
    client: AsyncClient,
) -> None:
    agent = await _agent(client)
    suite_response = await client.post(
        "/evaluation-suites",
        json={
            "name": "Calculator Regression",
            "description": "Real arithmetic execution",
            "agent_id": agent["id"],
            "cases": [
                {
                    "name": "Calculator basic arithmetic",
                    "input": "Calculate 128 * 37 + 456",
                    "graders": [
                        {"type": "run_status"},
                        {"type": "final_output_non_empty"},
                        {"type": "contains", "value": "5192"},
                        {"type": "tool_selected", "tool_name": "calculator"},
                        {
                            "type": "tool_not_selected",
                            "tool_name": "knowledge_search",
                        },
                        {"type": "max_steps", "maximum": 3},
                    ],
                },
                {
                    "name": "Intentional wrong expectation",
                    "input": "Calculate 128 * 37 + 456",
                    "graders": [
                        {"type": "run_status"},
                        {"type": "exact_match", "value": "9999"},
                    ],
                },
            ],
        },
    )
    assert suite_response.status_code == 201, suite_response.text
    suite = suite_response.json()
    accepted = await client.post(
        f"/evaluation-suites/{suite['id']}/runs",
        headers={"Idempotency-Key": "calculator-eval-1"},
    )
    assert accepted.status_code == 202
    duplicate = await client.post(
        f"/evaluation-suites/{suite['id']}/runs",
        headers={"Idempotency-Key": "calculator-eval-1"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == accepted.json()["id"]
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["status"] == "completed"
    assert evaluation["total_cases"] == evaluation["completed_cases"] == 2
    assert evaluation["passed_cases"] == 1
    assert evaluation["failed_cases"] == 1
    assert evaluation["error_cases"] == 0
    assert evaluation["pass_rate"] == 0.5

    results = (await client.get(f"/evaluation-runs/{evaluation['id']}/results")).json()
    assert [result["status"] for result in results] == ["pass", "fail"]
    assert results[0]["actual_output"] == "5192"
    assert results[1]["actual_output"] == "5192"
    failed_exact = next(
        grader
        for grader in results[1]["grader_results"]
        if grader["grader_type"] == "exact_match"
    )
    assert failed_exact["outcome"] == "fail"
    assert failed_exact["expected"]["value"] == "9999"
    assert failed_exact["actual"] == "5192"

    actual_run = (await client.get(f"/runs/{results[0]['run_id']}")).json()
    assert actual_run["run_kind"] == "evaluation"
    events = (await client.get(f"/runs/{actual_run['id']}/events")).json()
    assert any(event["type"] == "tool.completed" for event in events)
    observability = (
        await client.get(f"/runs/{actual_run['id']}/observability")
    ).json()
    assert observability["tool_calls"]["succeeded"] == 1

    dashboard = (await client.get("/observability/dashboard")).json()
    assert dashboard["total_runs"] == 0
    assert dashboard["recent_runs"] == []
    listed_agents = (await client.get("/agents")).json()
    assert [listed["id"] for listed in listed_agents] == [agent["id"]]


@pytest.mark.asyncio
async def test_evaluation_memory_setup_is_real_and_isolated_from_source_agent(
    client: AsyncClient,
) -> None:
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Memory Regression",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Recall isolated codename",
                        "input": "What is the project codename?",
                        "setup": {
                            "memories": [
                                {
                                    "content": "The project codename is Aurora",
                                    "importance": 0.9,
                                }
                            ]
                        },
                        "graders": [
                            {"type": "run_status"},
                            {"type": "memory_retrieved"},
                            {"type": "contains", "value": "Aurora"},
                        ],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["passed_cases"] == 1
    result = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    assert result["status"] == "pass"
    assert "Aurora" in result["actual_output"]
    events = (await client.get(f"/runs/{result['run_id']}/events")).json()
    assert any(event["type"] == "memory.retrieved" for event in events)
    assert (await client.get(f"/agents/{agent['id']}/memories")).json() == []


@pytest.mark.asyncio
async def test_evaluation_clone_preserves_disabled_memory_configuration(
    client: AsyncClient,
) -> None:
    agent = await _agent(client, tools=[], memory_enabled=False)
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Disabled Memory configuration",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "No Memory override",
                        "input": "hello",
                        "graders": [{"type": "run_status"}],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    result = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    actual_run = (await client.get(f"/runs/{result['run_id']}")).json()
    evaluation_agent = (await client.get(f"/agents/{actual_run['agent_id']}")).json()
    assert evaluation_agent["memory_enabled"] is False


@pytest.mark.asyncio
async def test_rag_graders_use_completed_retrieval_and_citation_provenance(
    client: AsyncClient,
) -> None:
    base = (
        await client.post(
            "/knowledge-bases",
            json={"name": "Evaluation RAG", "description": "fixture"},
        )
    ).json()
    uploaded = await client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={
            "file": (
                "evaluation-source.md",
                b"# Release fact\nThe deterministic launch codename is Blue Harbor.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 202
    job_id = uploaded.json()["ingestion_job"]["id"]
    for _ in range(200):
        job = (await client.get(f"/ingestion-jobs/{job_id}")).json()
        if job["state"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    assert job["state"] == "completed"

    agent = await _agent(
        client,
        tools=["knowledge_search"],
        knowledge_base_ids=[base["id"]],
    )
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "RAG Regression",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Expected source retrieval",
                        "input": "What is the deterministic launch codename?",
                        "graders": [
                            {"type": "run_status"},
                            {"type": "final_output_non_empty"},
                            {
                                "type": "tool_selected",
                                "tool_name": "knowledge_search",
                            },
                            {
                                "type": "retrieval_hit",
                                "expected_source": "upload://evaluation-source.md",
                            },
                            {
                                "type": "citation",
                                "expected_source": "upload://evaluation-source.md",
                            },
                        ],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["passed_cases"] == 1
    result = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    assert result["status"] == "pass"
    assert all(grader["outcome"] == "pass" for grader in result["grader_results"])


@pytest.mark.asyncio
async def test_suite_edits_do_not_rewrite_persisted_run_snapshots(
    client: AsyncClient,
) -> None:
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Versioned Suite",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Original case",
                        "input": "hello",
                        "graders": [{"type": "run_status"}],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    result_before = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    updated = await client.patch(
        f"/evaluation-cases/{suite['cases'][0]['id']}",
        json={"name": "Edited later", "input": "changed"},
    )
    assert updated.status_code == 200
    result_after = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    assert result_before["case_snapshot"] == result_after["case_snapshot"]
    assert result_after["case_snapshot"]["name"] == "Original case"


@pytest.mark.asyncio
async def test_zero_case_suite_completes_with_na_pass_rate(client: AsyncClient) -> None:
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={"name": "Empty suite", "agent_id": agent["id"], "cases": []},
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["status"] == "completed"
    assert evaluation["total_cases"] == evaluation["completed_cases"] == 0
    assert evaluation["pass_rate"] is None


@pytest.mark.asyncio
async def test_case_execution_error_does_not_leave_evaluation_stuck(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/agents",
        json={
            "name": "Unconfigured OpenAI Agent",
            "instructions": "Test infrastructure errors.",
            "runtime_mode": "openai",
            "tools": [],
        },
    )
    agent = response.json()
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Infrastructure error",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Cannot start provider",
                        "input": "hello",
                        "graders": [{"type": "run_status"}],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["status"] == "completed"
    assert evaluation["error_cases"] == 1
    assert evaluation["failed_cases"] == 0
    result = (
        await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    ).json()[0]
    assert result["status"] == "error"
    assert "could not execute" in result["error"]


@pytest.mark.asyncio
async def test_evaluation_cancellation_stops_the_active_real_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def block(self: MockProvider, context: object) -> object:
        del self, context
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(MockProvider, "decide", block)
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Cancellation",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Blocking case",
                        "input": "block",
                        "graders": [{"type": "run_status"}],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0.02)
    cancelled = await client.post(f"/evaluation-runs/{accepted.json()['id']}/cancel")
    assert cancelled.status_code == 202
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    assert evaluation["status"] == "cancelled"
    results = (await client.get(f"/evaluation-runs/{evaluation['id']}/results")).json()
    assert results[0]["status"] == "error"
    actual_run = (await client.get(f"/runs/{results[0]['run_id']}")).json()
    assert actual_run["status"] == "cancelled"


@pytest.mark.asyncio
async def test_invalid_idempotency_key_is_rejected(client: AsyncClient) -> None:
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={"name": "Key validation", "agent_id": agent["id"], "cases": []},
        )
    ).json()
    response = await client.post(
        f"/evaluation-suites/{suite['id']}/runs",
        headers={"Idempotency-Key": "unsafe key with spaces"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_concurrent_idempotent_starts_create_one_evaluation_run(
    client: AsyncClient,
) -> None:
    agent = await _agent(client, tools=[])
    suite = (
        await client.post(
            "/evaluation-suites",
            json={"name": "Concurrent key", "agent_id": agent["id"], "cases": []},
        )
    ).json()
    responses = await asyncio.gather(
        *[
            client.post(
                f"/evaluation-suites/{suite['id']}/runs",
                headers={"Idempotency-Key": "concurrent-evaluation-1"},
            )
            for _ in range(5)
        ]
    )
    assert {response.status_code for response in responses} == {202}
    assert len({response.json()["id"] for response in responses}) == 1


@pytest.mark.asyncio
async def test_evaluation_suite_and_case_crud_are_persisted(client: AsyncClient) -> None:
    agent = await _agent(client, tools=[])
    created = await client.post(
        "/evaluation-suites",
        json={"name": "CRUD suite", "agent_id": agent["id"], "cases": []},
    )
    assert created.status_code == 201
    suite = created.json()

    updated = await client.patch(
        f"/evaluation-suites/{suite['id']}",
        json={"name": "CRUD suite updated", "description": "Persisted"},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == suite["revision"] + 1

    case = await client.post(
        f"/evaluation-suites/{suite['id']}/cases",
        json={
            "name": "Created case",
            "input": "hello",
            "graders": [{"type": "run_status"}],
        },
    )
    assert case.status_code == 201
    changed = await client.patch(
        f"/evaluation-cases/{case.json()['id']}",
        json={"name": "Changed case", "enabled": False},
    )
    assert changed.status_code == 200
    assert changed.json()["enabled"] is False
    case_deleted = await client.delete(f"/evaluation-cases/{case.json()['id']}")
    assert case_deleted.status_code == 204

    fetched = await client.get(f"/evaluation-suites/{suite['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "CRUD suite updated"
    assert fetched.json()["cases"] == []

    deleted = await client.delete(f"/evaluation-suites/{suite['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/evaluation-suites/{suite['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_sensitive_definitions_are_rejected_and_outputs_are_redacted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _agent(client, tools=[])
    secret = "api_key=super-secret-value"
    rejected = await client.post(
        "/evaluation-suites",
        json={
            "name": "Rejected secret",
            "agent_id": agent["id"],
            "cases": [
                {
                    "name": "Secret-shaped expectation",
                    "input": "hello",
                    "graders": [{"type": "exact_match", "value": secret}],
                }
            ],
        },
    )
    assert rejected.status_code == 422
    assert "super-secret-value" not in rejected.text

    sensitive_agent = (
        await client.post(
            "/agents",
            json={
                "name": "Sensitive Agent",
                "instructions": secret,
                "runtime_mode": "mock",
                "tools": [],
            },
        )
    ).json()
    safe_suite = (
        await client.post(
            "/evaluation-suites",
            json={"name": "Safe suite", "agent_id": sensitive_agent["id"], "cases": []},
        )
    ).json()
    sensitive_start = await client.post(
        f"/evaluation-suites/{safe_suite['id']}/runs"
    )
    assert sensitive_start.status_code == 422
    assert "super-secret-value" not in sensitive_start.text

    async def secret_output(self: MockProvider, context: object) -> AgentDecision:
        del self, context
        return AgentDecision(action="final", final_output=secret)

    monkeypatch.setattr(MockProvider, "decide", secret_output)
    suite = (
        await client.post(
            "/evaluation-suites",
            json={
                "name": "Redacted output",
                "agent_id": agent["id"],
                "cases": [
                    {
                        "name": "Safe definition",
                        "input": "hello",
                        "graders": [{"type": "final_output_non_empty"}],
                    }
                ],
            },
        )
    ).json()
    accepted = await client.post(f"/evaluation-suites/{suite['id']}/runs")
    evaluation = await _wait_evaluation(client, accepted.json()["id"])
    response = await client.get(f"/evaluation-runs/{evaluation['id']}/results")
    assert response.status_code == 200
    assert "super-secret-value" not in response.text
    result = response.json()[0]
    assert result["actual_output"] == "api_key=[REDACTED]"
    assert result["grader_results"][0]["actual"]["non_empty"] is True


@pytest.mark.asyncio
async def test_recovery_marks_interrupted_case_and_underlying_run_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'recovery.db').as_posix()}",
        knowledge_storage_path=str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        await app.state.evaluation_worker.stop()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agent = await _agent(client, tools=[])
            suite = (
                await client.post(
                    "/evaluation-suites",
                    json={
                        "name": "Recovery",
                        "agent_id": agent["id"],
                        "cases": [
                            {
                                "name": "Interrupted case",
                                "input": "hello",
                                "graders": [{"type": "run_status"}],
                            }
                        ],
                    },
                )
            ).json()

            service = app.state.evaluation_service
            repository = service._repository
            evaluation = await service.start_run(UUID(suite["id"]), "recovery-1")
            execution = await repository.get_execution(evaluation.id)
            case_snapshot = execution.suite_snapshot["cases"][0]
            case_result_id = await repository.begin_case(
                evaluation.id, UUID(case_snapshot["id"]), case_snapshot
            )
            evaluation_agent = await service._repositories.create_evaluation_agent(
                await service._agent_service.get_agent(UUID(agent["id"]))
            )
            actual_run = await service._repositories.create_run(
                evaluation_agent.id,
                "interrupted",
                run_kind=RunKind.EVALUATION,
            )
            await repository.attach_case_execution(
                evaluation.id, case_result_id, evaluation_agent.id, actual_run.id
            )
            await repository.mark_running(evaluation.id)

            recovered = await service.recover_runs()
            assert recovered == [evaluation.id]
            assert (
                await service._agent_service.get_run(actual_run.id)
            ).status == RunStatus.FAILED
            await service.process_run(evaluation.id)

            finished = await service.get_run(evaluation.id)
            assert finished.status == "completed"
            results = await service.list_results(evaluation.id)
            assert len(results) == 1
            assert results[0].status == "error"
            assert results[0].error == (
                "Evaluation worker restarted while this case was executing."
            )
