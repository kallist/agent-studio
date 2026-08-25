from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.contracts import (
    AgentCreate,
    AgentEvent,
    AgentRun,
    CancellationToken,
    EmbeddingVector,
    EventSink,
    IngestionState,
    KnowledgeBaseCreate,
    KnowledgeSearchRequest,
    RetrievalFilters,
    RunStatus,
    RuntimeInput,
    RuntimeMode,
    VectorMatch,
)
from app.evaluation.contracts import EvaluationAggregate, GraderMetric
from app.knowledge.chunking import ChunkDraft
from app.knowledge.vector_store import PgVectorStore
from app.memory.policy import MemoryPolicy
from app.persistence.models import (
    AgentModel,
    ChunkModel,
    DocumentModel,
    EvaluationCaseResultModel,
    EvaluationRunModel,
    GraderResultModel,
    IngestionJobModel,
    MemoryModel,
    RunEventModel,
    RunModel,
)
from app.runtime.mock import MockRuntime

pytestmark = [pytest.mark.postgresql, pytest.mark.asyncio]


async def _create_agent(
    client: AsyncClient,
    name: str,
    *,
    tools: list[str] | None = None,
    knowledge_base_ids: list[str] | None = None,
) -> dict[str, object]:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "instructions": "Use configured tools and persisted context deterministically.",
            "runtime_mode": "mock",
            "tools": tools or [],
            "knowledge_base_ids": knowledge_base_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wait_run(client: AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(300):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("PostgreSQL-backed Agent Run did not reach a terminal state.")


async def _run(
    client: AsyncClient,
    agent_id: object,
    user_input: str,
) -> dict[str, object]:
    accepted = await client.post(f"/agents/{agent_id}/runs", json={"input": user_input})
    assert accepted.status_code == 202, accepted.text
    return await _wait_run(client, accepted.json()["id"])


async def _wait_evaluation(client: AsyncClient, evaluation_run_id: str) -> dict[str, object]:
    for _ in range(500):
        response = await client.get(f"/evaluation-runs/{evaluation_run_id}")
        assert response.status_code == 200
        evaluation = response.json()
        if evaluation["status"] in {"completed", "failed", "cancelled"}:
            return evaluation
        await asyncio.sleep(0.01)
    pytest.fail("PostgreSQL-backed Evaluation did not reach a terminal state.")


class _ConcurrentFinalizationRuntime:
    def __init__(self, delegate: MockRuntime) -> None:
        self._delegate = delegate
        self._ready = 0
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
            self._ready += 1
            if self._ready == 2:
                self.all_ready.set()
        await self.release.wait()
        return result


class _FailingVectorWrite:
    def __init__(self, delegate: PgVectorStore) -> None:
        self._delegate = delegate

    async def initialize(self) -> None:
        await self._delegate.initialize()

    async def upsert(self, records: list[EmbeddingVector]) -> None:
        del records
        raise RuntimeError("simulated PostgreSQL vector write failure")

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        await self._delegate.delete_chunks(chunk_ids)

    async def delete_document(self, document_id: UUID) -> None:
        await self._delegate.delete_document(document_id)

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[VectorMatch]:
        return await self._delegate.search(knowledge_base_ids, query_vector, top_k, filters)


async def _replacement_job(app: FastAPI, document_id: str) -> UUID:
    sessions = app.state.agent_service._repositories._sessions
    async with sessions() as session:
        model = IngestionJobModel(
            document_id=document_id,
            state=IngestionState.QUEUED.value,
        )
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return UUID(model.id)


async def test_postgresql_memory_row_locks_prove_both_orderings(
    postgres_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = postgres_app.state.agent_service._repositories
    store = postgres_app.state.agent_service._memory_store
    policy = MemoryPolicy()
    original_acquire = repositories._acquire_agent_memory_ownership

    disable_agent = await repositories.create_agent(
        AgentCreate(name="PostgreSQL disable wins", instructions="Remember facts.", tools=[])
    )
    disable_run = await repositories.create_run(
        disable_agent.id, "Remember that project codename is Atlas."
    )
    await repositories.update_run(disable_run.id, RunStatus.RUNNING)
    disable_candidate = policy.propose_write(
        agent_id=disable_agent.id,
        run_id=disable_run.id,
        user_input=disable_run.input,
        now=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert disable_candidate is not None
    disable_has_lock = asyncio.Event()
    allow_disable_commit = asyncio.Event()
    finalization_attempted = asyncio.Event()
    finalization_has_lock = asyncio.Event()

    async def disable_first(session: AsyncSession, agent_id: UUID) -> AgentModel:
        is_disable = (
            asyncio.current_task() is not None
            and asyncio.current_task().get_name() == "disable-first"
        )
        if not is_disable:
            finalization_attempted.set()
        agent = await original_acquire(session, agent_id)
        if is_disable:
            disable_has_lock.set()
            await allow_disable_commit.wait()
        else:
            finalization_has_lock.set()
        return agent

    monkeypatch.setattr(repositories, "_acquire_agent_memory_ownership", disable_first)
    disable_task = asyncio.create_task(
        repositories.set_memory_enabled(disable_agent.id, False), name="disable-first"
    )
    await asyncio.wait_for(disable_has_lock.wait(), timeout=3)
    finalization_task = asyncio.create_task(
        repositories.finish_completed_run_with_memory(
            disable_run.id,
            disable_agent.id,
            AgentEvent(run_id=disable_run.id, sequence=1, type="run.completed"),
            output="done",
            candidate=disable_candidate,
        ),
        name="finalization-second",
    )
    await asyncio.wait_for(finalization_attempted.wait(), timeout=3)
    await asyncio.sleep(0.05)
    assert not finalization_has_lock.is_set()
    allow_disable_commit.set()
    await disable_task
    disable_events = await finalization_task
    assert [event.type for event in disable_events] == ["run.completed"]
    assert await store.list(disable_agent.id) == []

    monkeypatch.setattr(repositories, "_acquire_agent_memory_ownership", original_acquire)
    final_agent = await repositories.create_agent(
        AgentCreate(name="PostgreSQL finalization wins", instructions="Remember facts.", tools=[])
    )
    final_run = await repositories.create_run(
        final_agent.id, "Remember that deployment region is west."
    )
    await repositories.update_run(final_run.id, RunStatus.RUNNING)
    final_candidate = policy.propose_write(
        agent_id=final_agent.id,
        run_id=final_run.id,
        user_input=final_run.input,
        now=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert final_candidate is not None
    finalization_has_lock = asyncio.Event()
    allow_finalization_commit = asyncio.Event()
    disable_attempted = asyncio.Event()
    disable_has_lock = asyncio.Event()

    async def finalization_first(session: AsyncSession, agent_id: UUID) -> AgentModel:
        is_disable = (
            asyncio.current_task() is not None
            and asyncio.current_task().get_name() == "disable-second"
        )
        if is_disable:
            disable_attempted.set()
        agent = await original_acquire(session, agent_id)
        if is_disable:
            disable_has_lock.set()
        else:
            finalization_has_lock.set()
            await allow_finalization_commit.wait()
        return agent

    monkeypatch.setattr(repositories, "_acquire_agent_memory_ownership", finalization_first)
    finalization_task = asyncio.create_task(
        repositories.finish_completed_run_with_memory(
            final_run.id,
            final_agent.id,
            AgentEvent(run_id=final_run.id, sequence=1, type="run.completed"),
            output="done",
            candidate=final_candidate,
        ),
        name="finalization-first",
    )
    await asyncio.wait_for(finalization_has_lock.wait(), timeout=3)
    disable_task = asyncio.create_task(
        repositories.set_memory_enabled(final_agent.id, False), name="disable-second"
    )
    await asyncio.wait_for(disable_attempted.wait(), timeout=3)
    await asyncio.sleep(0.05)
    assert not disable_has_lock.is_set()
    allow_finalization_commit.set()
    final_events = await finalization_task
    await disable_task
    assert [event.type for event in final_events] == ["memory.written", "run.completed"]
    assert len(await store.list(final_agent.id)) == 1
    assert (await repositories.get_agent(final_agent.id)).memory_enabled is False

    monkeypatch.setattr(repositories, "_acquire_agent_memory_ownership", original_acquire)
    rollback_agent = await repositories.create_agent(
        AgentCreate(name="PostgreSQL atomic rollback", instructions="Remember facts.", tools=[])
    )
    rollback_run = await repositories.create_run(
        rollback_agent.id, "Remember that project codename is Rollback."
    )
    await repositories.update_run(rollback_run.id, RunStatus.RUNNING)
    existing_event = AgentEvent(run_id=rollback_run.id, sequence=1, type="run.started")
    await repositories.append_event(existing_event)
    rollback_candidate = policy.propose_write(
        agent_id=rollback_agent.id,
        run_id=rollback_run.id,
        user_input=rollback_run.input,
        now=datetime(2026, 8, 21, tzinfo=UTC),
    )
    assert rollback_candidate is not None
    with pytest.raises(IntegrityError):
        await repositories.finish_completed_run_with_memory(
            rollback_run.id,
            rollback_agent.id,
            AgentEvent(
                event_id=existing_event.event_id,
                run_id=rollback_run.id,
                sequence=2,
                type="run.completed",
            ),
            output="done",
            candidate=rollback_candidate,
        )
    assert await store.list(rollback_agent.id) == []
    assert (await repositories.get_run(rollback_run.id)).status is RunStatus.RUNNING
    assert [event.type for event in await repositories.list_events(rollback_run.id)] == [
        "run.started"
    ]


async def test_two_concurrent_postgresql_runs_dedupe_complete_application_path(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
) -> None:
    service = postgres_app.state.agent_service
    original_runtime = service._runtimes[RuntimeMode.MOCK]
    assert isinstance(original_runtime, MockRuntime)
    runtime = _ConcurrentFinalizationRuntime(original_runtime)
    service._runtimes[RuntimeMode.MOCK] = runtime
    agent = await _create_agent(postgres_client, "PostgreSQL concurrent memory")
    accepted = await asyncio.gather(
        *[
            postgres_client.post(
                f"/agents/{agent['id']}/runs",
                json={"input": "Remember that project codename is Atlas."},
            )
            for _ in range(2)
        ]
    )
    assert [response.status_code for response in accepted] == [202, 202]
    await asyncio.wait_for(runtime.all_ready.wait(), timeout=3)
    runtime.release.set()
    runs = await asyncio.gather(
        *[_wait_run(postgres_client, response.json()["id"]) for response in accepted]
    )
    assert [run["status"] for run in runs] == ["completed", "completed"]
    memories = (await postgres_client.get(f"/agents/{agent['id']}/memories")).json()
    assert len(memories) == 1
    memory_ids: list[str] = []
    for run in runs:
        events = (await postgres_client.get(f"/runs/{run['id']}/events")).json()
        assert [event["type"] for event in events][-2:] == [
            "memory.written",
            "run.completed",
        ]
        memory_ids.append(events[-2]["payload"]["memory_id"])
    assert memory_ids == [memories[0]["id"], memories[0]["id"]]
    deleted = await postgres_client.delete(f"/agents/{agent['id']}/memories/{memories[0]['id']}")
    assert deleted.status_code == 204
    assert (await postgres_client.get(f"/agents/{agent['id']}/memories")).json() == []


async def test_postgresql_ingestion_claim_and_generation_consistency(
    postgres_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = postgres_app.state.knowledge_service
    repository = service._repository
    sessions = repository._sessions
    base = await service.create_base(
        KnowledgeBaseCreate(name="PostgreSQL generations", description="transaction test")
    )
    accepted = await service.queue_upload(
        base.id,
        "generation.txt",
        "text/plain",
        b"stable-completed-generation remains trusted evidence",
    )
    for _ in range(300):
        initial_job = await service.get_job(accepted.ingestion_job.id)
        if initial_job.state in {IngestionState.COMPLETED, IngestionState.FAILED}:
            break
        await asyncio.sleep(0.01)
    assert initial_job.state is IngestionState.COMPLETED
    before = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="stable-completed-generation", top_k=1),
    )
    assert before.results and "stable-completed-generation" in before.results[0].content

    async with sessions() as session:
        storage_path = await session.scalar(
            select(DocumentModel.storage_path).where(DocumentModel.id == str(accepted.document.id))
        )
    assert storage_path is not None
    await asyncio.to_thread(
        Path(storage_path).write_bytes,
        b"failed-vector-generation must remain invisible",
    )
    failed_vector_job = await _replacement_job(postgres_app, str(accepted.document.id))
    real_store = service._vector_store
    assert isinstance(real_store, PgVectorStore)
    service._vector_store = _FailingVectorWrite(real_store)
    with pytest.raises(RuntimeError, match="simulated PostgreSQL vector write failure"):
        await service.process_job(failed_vector_job)
    assert (await service.get_job(failed_vector_job)).state is IngestionState.FAILED
    after_vector_failure = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="failed-vector-generation", top_k=5),
    )
    assert all(
        "failed-vector-generation" not in item.content for item in after_vector_failure.results
    )
    preserved = await service.search(
        [base.id], KnowledgeSearchRequest(query="stable-completed-generation", top_k=1)
    )
    assert preserved.results and "stable-completed-generation" in preserved.results[0].content

    service._vector_store = real_store
    await asyncio.to_thread(
        Path(storage_path).write_bytes,
        b"failed-activation-generation must remain invisible",
    )
    failed_activation_job = await _replacement_job(postgres_app, str(accepted.document.id))
    original_activate: Callable[[UUID], Awaitable[None]] = repository.activate_job

    async def fail_activation(
        job_id: UUID,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        del job_id, embedding_provider, embedding_model, embedding_dimensions
        raise RuntimeError("simulated PostgreSQL activation failure")

    monkeypatch.setattr(repository, "activate_job", fail_activation)
    with pytest.raises(RuntimeError, match="simulated PostgreSQL activation failure"):
        await service.process_job(failed_activation_job)
    assert (await service.get_job(failed_activation_job)).state is IngestionState.FAILED
    still_preserved = await service.search(
        [base.id], KnowledgeSearchRequest(query="stable-completed-generation", top_k=1)
    )
    assert still_preserved.results
    assert "stable-completed-generation" in still_preserved.results[0].content

    monkeypatch.setattr(repository, "activate_job", original_activate)
    await asyncio.to_thread(
        Path(storage_path).write_bytes,
        b"new-successful-generation is now active evidence",
    )
    successful_job = await _replacement_job(postgres_app, str(accepted.document.id))
    await service.process_job(successful_job)
    assert (await service.get_job(successful_job)).state is IngestionState.COMPLETED
    replaced = await service.search(
        [base.id], KnowledgeSearchRequest(query="new-successful-generation", top_k=1)
    )
    assert replaced.results and "new-successful-generation" in replaced.results[0].content
    assert "stable-completed-generation" not in replaced.results[0].content

    claim_document, first_claim_job = await repository.create_document_and_job(
        knowledge_base_id=base.id,
        filename="claim.txt",
        source="upload://claim.txt",
        mime_type="text/plain",
        size_bytes=5,
        storage_path=Path(storage_path),
    )
    second_claim_job = await _replacement_job(postgres_app, str(claim_document.id))
    claims = await asyncio.gather(
        repository.mark_processing(first_claim_job.id),
        repository.mark_processing(second_claim_job),
    )
    assert sum(claim is not None for claim in claims) == 1
    claim_states = {
        (await repository.get_job(first_claim_job.id)).state,
        (await repository.get_job(second_claim_job)).state,
    }
    assert claim_states == {IngestionState.PROCESSING, IngestionState.FAILED}


async def test_failed_postgresql_vectors_are_invisible_to_all_retrieval_boundaries(
    postgres_app: FastAPI,
) -> None:
    service = postgres_app.state.knowledge_service
    repository = service._repository
    sessions = repository._sessions
    base = await service.create_base(
        KnowledgeBaseCreate(name="Dirty PostgreSQL generation", description="fail closed")
    )
    document, _ = await repository.create_document_and_job(
        knowledge_base_id=base.id,
        filename="dirty.txt",
        source="upload://dirty.txt",
        mime_type="text/plain",
        size_bytes=10,
        storage_path=Path("unused-dirty-test-path"),
    )
    failed_job_id = uuid4()
    dirty_chunk_id = uuid4()
    async with sessions() as session:
        session.add(
            IngestionJobModel(
                id=str(failed_job_id),
                document_id=str(document.id),
                state=IngestionState.FAILED.value,
                error="fixture failure",
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            ChunkModel(
                id=str(dirty_chunk_id),
                knowledge_base_id=str(base.id),
                document_id=str(document.id),
                ingestion_job_id=str(failed_job_id),
                chunk_index=900,
                content="dirty-failed-exclusive-token must never be visible",
                token_count=7,
                metadata_json="{}",
            )
        )
        await session.commit()
    vector = (await service._embeddings.embed(["dirty-failed-exclusive-token"]))[0]
    await service._vector_store.upsert(
        [
            EmbeddingVector(
                chunk_id=dirty_chunk_id,
                vector=vector,
                provider=service._embeddings.name,
                model=service._embeddings.model,
            )
        ]
    )
    for hybrid in (False, True):
        response = await service.search(
            [base.id],
            KnowledgeSearchRequest(query="dirty-failed-exclusive-token", top_k=5, hybrid=hybrid),
        )
        assert response.results == []
    assert await repository.list_chunk_candidates([base.id], None) == []
    assert await repository.hydrate_matches([VectorMatch(chunk_id=dirty_chunk_id, score=1)]) == []


async def test_pgvector_thousand_chunk_insert_and_retrieval_sanity(
    postgres_app: FastAPI,
) -> None:
    service = postgres_app.state.knowledge_service
    repository = service._repository
    base = await service.create_base(
        KnowledgeBaseCreate(name="PostgreSQL scale sanity", description="1000 chunks")
    )
    _, job = await repository.create_document_and_job(
        knowledge_base_id=base.id,
        filename="scale.txt",
        source="upload://scale.txt",
        mime_type="text/plain",
        size_bytes=1_000,
        storage_path=Path("unused-scale-test-path"),
    )
    claimed = await repository.mark_processing(job.id)
    assert claimed is not None
    contents = [
        f"deterministic scale chunk {index} unique_item_{index} postgres vector evidence"
        for index in range(1_000)
    ]
    drafts = [
        ChunkDraft(
            index=index,
            content=content,
            token_count=len(content.split()),
            metadata={"ordinal": index, "kind": "scale_sanity"},
        )
        for index, content in enumerate(contents)
    ]
    async with asyncio.timeout(60):
        chunks = await repository.stage_chunks(job.id, claimed, drafts)
        vectors = await service._embeddings.embed(contents)
        await service._vector_store.upsert(
            [
                EmbeddingVector(
                    chunk_id=chunk.id,
                    vector=vector,
                    provider=service._embeddings.name,
                    model=service._embeddings.model,
                    metadata=chunk.metadata,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        await repository.activate_job(job.id)
        result = await service.search(
            [base.id],
            KnowledgeSearchRequest(query=contents[731], top_k=3, hybrid=False),
        )
    assert result.results
    assert result.results[0].chunk_id == chunks[731].id
    assert result.results[0].metadata == {"ordinal": 731, "kind": "scale_sanity"}
    async with repository._sessions() as session:
        vector_count = await session.scalar(text("SELECT count(*) FROM rag_vectors"))
    assert vector_count == 1_000


async def test_evaluation_observability_redaction_and_calculator_on_postgresql(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
) -> None:
    agent = await _create_agent(
        postgres_client,
        "PostgreSQL evaluation calculator",
        tools=["calculator"],
    )
    suite_response = await postgres_client.post(
        "/evaluation-suites",
        json={
            "name": "PostgreSQL Calculator Evaluation",
            "agent_id": agent["id"],
            "cases": [
                {
                    "name": "correct",
                    "input": "Calculate 128 * 37 + 456",
                    "graders": [
                        {"type": "run_status"},
                        {"type": "exact_match", "value": "5192"},
                        {"type": "tool_selected", "tool_name": "calculator"},
                    ],
                },
                {
                    "name": "intentional mismatch",
                    "input": "Calculate 128 * 37 + 456",
                    "graders": [
                        {"type": "run_status"},
                        {"type": "exact_match", "value": "9999"},
                    ],
                },
                {
                    "name": "isolated memory",
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
                },
            ],
        },
    )
    assert suite_response.status_code == 201, suite_response.text
    accepted = await postgres_client.post(
        f"/evaluation-suites/{suite_response.json()['id']}/runs",
        headers={"Idempotency-Key": "postgres-calculator-evaluation"},
    )
    assert accepted.status_code == 202
    duplicate = await postgres_client.post(
        f"/evaluation-suites/{suite_response.json()['id']}/runs",
        headers={"Idempotency-Key": "postgres-calculator-evaluation"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == accepted.json()["id"]
    evaluation = await _wait_evaluation(postgres_client, accepted.json()["id"])
    assert evaluation["status"] == "completed"
    assert evaluation["passed_cases"] == 2
    assert evaluation["failed_cases"] == 1
    assert evaluation["error_cases"] == 0
    results = (await postgres_client.get(f"/evaluation-runs/{evaluation['id']}/results")).json()
    assert [result["status"] for result in results] == ["pass", "fail", "pass"]
    assert [result["actual_output"] for result in results[:2]] == ["5192", "5192"]
    assert "Aurora" in results[2]["actual_output"]
    memory_events = (await postgres_client.get(f"/runs/{results[2]['run_id']}/events")).json()
    assert any(event["type"] == "memory.retrieved" for event in memory_events)
    assert (
        next(
            grader
            for grader in results[1]["grader_results"]
            if grader["grader_type"] == "exact_match"
        )["outcome"]
        == "fail"
    )
    assert (await postgres_client.get("/observability/dashboard")).json()["total_runs"] == 0

    normal_run = await _run(postgres_client, agent["id"], "Calculate 128 * 37 + 456")
    assert normal_run["status"] == "completed"
    assert normal_run["output"] == "5192"
    metrics = (await postgres_client.get(f"/runs/{normal_run['id']}/observability")).json()
    assert metrics["tool_calls"] == {"total": 1, "succeeded": 1, "failed": 0}
    assert metrics["duration_ms"] >= 0
    events = (await postgres_client.get(f"/runs/{normal_run['id']}/events")).json()
    selected = next(event for event in events if event["type"] == "tool.selected")
    completed = next(event for event in events if event["type"] == "tool.completed")
    assert selected["tool_call_id"] == completed["tool_call_id"]

    repositories = postgres_app.state.agent_service._repositories
    redaction_agent = await repositories.create_agent(
        AgentCreate(name="PostgreSQL redaction", instructions="Protect secrets.", tools=[])
    )
    redaction_run = await repositories.create_run(redaction_agent.id, "redact")
    await repositories.update_run(redaction_run.id, RunStatus.RUNNING)
    await repositories.append_event(
        AgentEvent(
            run_id=redaction_run.id,
            sequence=1,
            type="tool.completed",
            payload={
                "authorization": "Bearer postgres-secret",
                "nested": {"api_key": "postgres-api-key"},
            },
        )
    )
    await repositories.finish_run(
        redaction_run.id,
        RunStatus.FAILED,
        AgentEvent(
            run_id=redaction_run.id,
            sequence=2,
            type="run.failed",
            payload={"error": "password=postgres-password"},
        ),
        error="authorization: Bearer persisted-postgres-secret",
    )
    async with repositories._sessions() as session:
        raw_events = "\n".join(
            await session.scalars(
                select(RunEventModel.payload_json).where(
                    RunEventModel.run_id == str(redaction_run.id)
                )
            )
        )
        raw_error = await session.scalar(
            select(RunModel.error).where(RunModel.id == str(redaction_run.id))
        )
        persisted_counts = {
            "evaluation_runs": await session.scalar(select(func.count(EvaluationRunModel.id))),
            "case_results": await session.scalar(select(func.count(EvaluationCaseResultModel.id))),
            "grader_results": await session.scalar(select(func.count(GraderResultModel.id))),
            "normal_memories": await session.scalar(
                select(func.count(MemoryModel.id)).where(MemoryModel.agent_id == str(agent["id"]))
            ),
        }
    assert "postgres-secret" not in raw_events
    assert "postgres-api-key" not in raw_events
    assert "postgres-password" not in raw_events
    assert raw_error == "authorization:[REDACTED]"
    assert persisted_counts == {
        "evaluation_runs": 1,
        "case_results": 3,
        "grader_results": 8,
        "normal_memories": 0,
    }


async def test_evaluation_suite_and_case_crud_on_postgresql(
    postgres_client: AsyncClient,
) -> None:
    agent = await _create_agent(postgres_client, "PostgreSQL evaluation CRUD")
    created = await postgres_client.post(
        "/evaluation-suites",
        json={"name": "PostgreSQL CRUD suite", "agent_id": agent["id"], "cases": []},
    )
    assert created.status_code == 201, created.text
    suite = created.json()

    updated = await postgres_client.patch(
        f"/evaluation-suites/{suite['id']}",
        json={"name": "PostgreSQL CRUD updated", "description": "Persisted on PostgreSQL"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == suite["revision"] + 1

    created_case = await postgres_client.post(
        f"/evaluation-suites/{suite['id']}/cases",
        json={
            "name": "PostgreSQL created case",
            "input": "hello",
            "graders": [{"type": "run_status"}],
        },
    )
    assert created_case.status_code == 201, created_case.text
    changed_case = await postgres_client.patch(
        f"/evaluation-cases/{created_case.json()['id']}",
        json={"name": "PostgreSQL changed case", "enabled": False},
    )
    assert changed_case.status_code == 200, changed_case.text
    assert changed_case.json()["enabled"] is False
    assert (
        await postgres_client.delete(f"/evaluation-cases/{created_case.json()['id']}")
    ).status_code == 204

    fetched = await postgres_client.get(f"/evaluation-suites/{suite['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "PostgreSQL CRUD updated"
    assert fetched.json()["cases"] == []
    assert (await postgres_client.delete(f"/evaluation-suites/{suite['id']}")).status_code == 204
    assert (await postgres_client.get(f"/evaluation-suites/{suite['id']}")).status_code == 404


async def test_postgresql_evaluation_aggregate_transaction_failure_rolls_back(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
) -> None:
    agent = await _create_agent(postgres_client, "PostgreSQL aggregate rollback")
    suite = (
        await postgres_client.post(
            "/evaluation-suites",
            json={"name": "Aggregate rollback", "agent_id": agent["id"], "cases": []},
        )
    ).json()
    accepted = await postgres_client.post(f"/evaluation-suites/{suite['id']}/runs")
    assert accepted.status_code == 202, accepted.text
    evaluation = await _wait_evaluation(postgres_client, accepted.json()["id"])
    assert evaluation["status"] == "completed"

    repository = postgres_app.state.evaluation_service._repository
    aggregate_columns = (
        EvaluationRunModel.total_cases,
        EvaluationRunModel.completed_cases,
        EvaluationRunModel.passed_cases,
        EvaluationRunModel.failed_cases,
        EvaluationRunModel.error_cases,
        EvaluationRunModel.pass_rate,
        EvaluationRunModel.average_duration_ms,
        EvaluationRunModel.p95_duration_ms,
        EvaluationRunModel.grader_metrics_json,
    )
    async with repository._sessions() as session:
        before = (
            await session.execute(
                select(*aggregate_columns).where(EvaluationRunModel.id == evaluation["id"])
            )
        ).one()
        await session.execute(
            text(
                """
                CREATE FUNCTION reject_evaluation_aggregate_test() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'forced evaluation aggregate transaction failure'
                        USING ERRCODE = '23514';
                END
                $$
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TRIGGER reject_evaluation_aggregate_test
                BEFORE UPDATE OF total_cases, completed_cases, passed_cases, failed_cases,
                    error_cases, pass_rate, average_duration_ms, p95_duration_ms,
                    grader_metrics_json
                ON evaluation_runs
                FOR EACH ROW EXECUTE FUNCTION reject_evaluation_aggregate_test()
                """
            )
        )
        await session.commit()

    try:
        with pytest.raises(SQLAlchemyError, match="forced evaluation aggregate"):
            await repository.update_aggregate(
                UUID(evaluation["id"]),
                EvaluationAggregate(
                    total_cases=9,
                    completed_cases=8,
                    passed_cases=7,
                    failed_cases=1,
                    error_cases=0,
                    pass_rate=0.875,
                    average_duration_ms=12.5,
                    p95_duration_ms=19.0,
                    grader_metrics={"run_status": GraderMetric(passed=7, total=8, pass_rate=0.875)},
                ),
            )
    finally:
        async with repository._sessions() as session:
            await session.execute(
                text("DROP TRIGGER IF EXISTS reject_evaluation_aggregate_test ON evaluation_runs")
            )
            await session.execute(
                text("DROP FUNCTION IF EXISTS reject_evaluation_aggregate_test()")
            )
            await session.commit()

    async with repository._sessions() as session:
        after = (
            await session.execute(
                select(*aggregate_columns).where(EvaluationRunModel.id == evaluation["id"])
            )
        ).one()
    assert after == before


async def test_explicit_unavailable_postgresql_never_falls_back_to_sqlite() -> None:
    from app.main import create_app

    unavailable = create_app(
        "postgresql+asyncpg://agent_studio_test:invalid@127.0.0.1:1/unavailable_test"
    )
    with pytest.raises((OSError, ConnectionError)):
        async with unavailable.router.lifespan_context(unavailable):
            pytest.fail("An unavailable explicit PostgreSQL URL must not start the app.")
