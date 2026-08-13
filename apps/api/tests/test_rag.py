from __future__ import annotations

import asyncio
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import (
    EmbeddingVector,
    KnowledgeBaseCreate,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RetrievalFilters,
    ToolCall,
    VectorMatch,
)
from app.domain.errors import KnowledgeValidationError, ToolExecutionError, ToolPermissionError
from app.knowledge.chunking import ChunkDraft
from app.knowledge.embeddings import DeterministicEmbeddingProvider
from app.knowledge.repository import KnowledgeRepository, StoredChunk, StoredDocument
from app.knowledge.service import KnowledgeService, _validate_upload
from app.knowledge.vector_store import PgVectorStore, SqlAlchemyVectorStore
from app.knowledge.worker import LocalIngestionWorker
from app.main import create_app
from app.persistence.database import build_database, settings
from app.persistence.models import Base, ChunkModel, EmbeddingModel, IngestionJobModel
from app.tools.knowledge_search import (
    KnowledgeSearchInput,
    KnowledgeSearchTool,
    bind_knowledge_bases,
)
from app.tools.registry import ToolExecutor, ToolRegistry

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "rag"


class FailingUpsertVectorStore:
    def __init__(self) -> None:
        self.received: list[EmbeddingVector] = []

    async def initialize(self) -> None:
        return None

    async def upsert(self, records: list[EmbeddingVector]) -> None:
        self.received = records
        raise RuntimeError("simulated vector write failure")

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        return None

    async def delete_document(self, document_id: UUID) -> None:
        return None

    async def search(
        self,
        knowledge_base_ids: list[UUID],
        query_vector: list[float],
        top_k: int,
        filters: RetrievalFilters | None = None,
    ) -> list[VectorMatch]:
        return []


class FailingActivationRepository(KnowledgeRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self.fail_next_activation = True
        self.activation_attempted = False
        self.staged_chunk_ids: list[UUID] = []

    async def stage_chunks(
        self, job_id: UUID, document: StoredDocument, drafts: list[ChunkDraft]
    ) -> list[StoredChunk]:
        chunks = await super().stage_chunks(job_id, document, drafts)
        self.staged_chunk_ids = [chunk.id for chunk in chunks]
        return chunks

    async def activate_job(self, job_id: UUID) -> None:
        self.activation_attempted = True
        if self.fail_next_activation:
            self.fail_next_activation = False
            raise RuntimeError("simulated activation failure")
        await super().activate_job(job_id)


class RaisingAfterActivationRepository(KnowledgeRepository):
    async def activate_job(self, job_id: UUID) -> None:
        await super().activate_job(job_id)
        raise RuntimeError("simulated lost activation acknowledgement")


class BlockingEmbeddingProvider(DeterministicEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.active_calls = 0
        self.max_active_calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.entered.set()
        try:
            await self.release.wait()
            return await super().embed(texts)
        finally:
            self.active_calls -= 1


async def create_base(client: AsyncClient, name: str = "RAG benchmark") -> dict[str, object]:
    response = await client.post(
        "/knowledge-bases", json={"name": name, "description": "Small retrieval corpus"}
    )
    assert response.status_code == 201
    return response.json()


async def upload_fixture(
    client: AsyncClient, knowledge_base_id: str, fixture: str, mime_type: str
) -> dict[str, object]:
    path = FIXTURES / fixture
    response = await client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": (path.name, path.read_bytes(), mime_type)},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["ingestion_job"]["state"] == "queued"
    await wait_for_job(client, str(payload["ingestion_job"]["id"]), "completed")
    return payload


async def wait_for_job(client: AsyncClient, job_id: str, expected: str) -> dict[str, object]:
    for _ in range(200):
        response = await client.get(f"/ingestion-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"completed", "failed"}:
            assert job["state"] == expected
            return job
        await asyncio.sleep(0.01)
    pytest.fail("ingestion did not reach a terminal state")


async def wait_for_repository_job(
    repository: KnowledgeRepository, job_id: UUID, terminal_states: set[str]
) -> str:
    for _ in range(300):
        state = (await repository.get_job(job_id)).state.value
        if state in terminal_states:
            return state
        await asyncio.sleep(0.01)
    pytest.fail(f"ingestion job {job_id} did not reach {sorted(terminal_states)}")


@pytest.mark.asyncio
async def test_rag_benchmark_recalls_expected_chunk_with_citations(client: AsyncClient) -> None:
    base = await create_base(client)
    base_id = str(base["id"])
    benchmark = json.loads((FIXTURES / "benchmark.json").read_text(encoding="utf-8"))
    for document in benchmark["documents"]:
        await upload_fixture(client, base_id, document["fixture"], document["mime_type"])

    recall_k = benchmark["recall_k"]
    hits = {"semantic": 0, "hybrid": 0}
    for case in benchmark["cases"]:
        for algorithm, hybrid in (("semantic", False), ("hybrid", True)):
            response = await client.post(
                f"/knowledge-bases/{base_id}/search",
                json={
                    "query": case["question"],
                    "top_k": recall_k,
                    "hybrid": hybrid,
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["algorithm"] == algorithm
            assert len(body["results"]) == recall_k
            rank = next(
                (
                    index
                    for index, result in enumerate(body["results"], start=1)
                    if result["document"] == case["expected_document"]
                    and case["expected_phrase"].lower() in result["content"].lower()
                ),
                None,
            )
            assert rank == case[f"expected_{algorithm}_rank"], (
                case["question"],
                algorithm,
                [result["document"] for result in body["results"]],
            )
            hits[algorithm] += int(rank is not None and rank <= recall_k)
            top = body["results"][0]
            assert top["source"].startswith("upload://")
            assert top["chunk_id"]
            assert isinstance(top["score"], float)

    case_count = len(benchmark["cases"])
    for algorithm in ("semantic", "hybrid"):
        recall_at_k = hits[algorithm] / case_count
        assert recall_at_k >= benchmark["minimum_recall_at_k"]


@pytest.mark.asyncio
async def test_failed_vector_write_never_exposes_chunks_or_citations(tmp_path: Path) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'failed-vector.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    repository = KnowledgeRepository(sessions)
    vector_store = FailingUpsertVectorStore()
    service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=DeterministicEmbeddingProvider(),
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    queued_jobs: list[UUID] = []
    service.bind_enqueue(queued_jobs.append)
    base = await service.create_base(
        KnowledgeBaseCreate(name="Failed ingestion", description="Regression corpus")
    )
    accepted = await service.queue_upload(
        base.id,
        "failed.txt",
        "text/plain",
        b"failed-vector-exclusive-token must never become cited evidence",
    )
    assert queued_jobs == [accepted.ingestion_job.id]

    with pytest.raises(RuntimeError, match="simulated vector write failure"):
        await service.process_job(accepted.ingestion_job.id)

    job = await service.get_job(accepted.ingestion_job.id)
    assert vector_store.received
    assert all(record.chunk_id for record in vector_store.received)
    assert job.state.value == "failed"

    direct = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="failed-vector-exclusive-token", top_k=5, hybrid=True),
    )
    assert direct.results == []

    with bind_knowledge_bases([base.id]):
        tool_result = await KnowledgeSearchTool(service).execute(
            KnowledgeSearchInput(query="failed-vector-exclusive-token", top_k=5)
        )
    assert tool_result.results == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_reingestion_preserves_last_completed_generation(tmp_path: Path) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'failed-reingestion.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    repository = KnowledgeRepository(sessions)
    embeddings = DeterministicEmbeddingProvider()
    completed_store = SqlAlchemyVectorStore(sessions)
    service = KnowledgeService(
        repository=repository,
        vector_store=completed_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    queued_jobs: list[UUID] = []
    service.bind_enqueue(queued_jobs.append)
    base = await service.create_base(
        KnowledgeBaseCreate(name="Versioned ingestion", description="Regression corpus")
    )
    accepted = await service.queue_upload(
        base.id,
        "versioned.txt",
        "text/plain",
        b"stable-completed-generation remains trusted evidence",
    )
    await service.process_job(accepted.ingestion_job.id)
    before = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="stable-completed-generation", top_k=1, hybrid=True),
    )
    assert before.results
    completed_chunk_id = before.results[0].chunk_id

    stored_file = next((tmp_path / "knowledge").iterdir())
    stored_file.write_bytes(b"failed-replacement-generation must remain hidden")
    async with sessions() as session:
        replacement = IngestionJobModel(document_id=str(accepted.document.id), state="queued")
        session.add(replacement)
        await session.commit()
        await session.refresh(replacement)
        replacement_job_id = UUID(replacement.id)

    failing_store = FailingUpsertVectorStore()
    replacement_service = KnowledgeService(
        repository=repository,
        vector_store=failing_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    with pytest.raises(RuntimeError, match="simulated vector write failure"):
        await replacement_service.process_job(replacement_job_id)

    assert (await replacement_service.get_job(replacement_job_id)).state.value == "failed"
    after = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="stable-completed-generation", top_k=3, hybrid=True),
    )
    assert after.results[0].chunk_id == completed_chunk_id
    assert all("failed-replacement-generation" not in result.content for result in after.results)

    # Duplicate delivery of a terminal job is an idempotent no-op.
    await service.process_job(accepted.ingestion_job.id)
    duplicate = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="stable-completed-generation", top_k=1, hybrid=True),
    )
    assert duplicate.results[0].chunk_id == completed_chunk_id

    stored_file.write_bytes(b"successful-replacement-generation is now trusted")
    async with sessions() as session:
        successful_replacement = IngestionJobModel(
            document_id=str(accepted.document.id), state="queued"
        )
        session.add(successful_replacement)
        await session.commit()
        await session.refresh(successful_replacement)
        successful_job_id = UUID(successful_replacement.id)
    await service.process_job(successful_job_id)
    current = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="successful-replacement-generation", top_k=1),
    )
    assert current.results[0].chunk_id != completed_chunk_id
    assert "successful-replacement-generation" in current.results[0].content
    assert "stable-completed-generation" not in current.results[0].content
    await engine.dispose()


@pytest.mark.asyncio
async def test_activation_failure_is_terminal_and_preserves_previous_generation(
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'failed-activation.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    embeddings = DeterministicEmbeddingProvider()
    repository = KnowledgeRepository(sessions)
    vector_store = SqlAlchemyVectorStore(sessions)
    service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    service.bind_enqueue(lambda _job_id: None)
    base = await service.create_base(
        KnowledgeBaseCreate(name="Activation failure", description="Regression corpus")
    )
    accepted = await service.queue_upload(
        base.id,
        "versioned.txt",
        "text/plain",
        b"previous-completed-generation remains searchable",
    )
    await service.process_job(accepted.ingestion_job.id)
    previous = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="previous-completed-generation", top_k=1),
    )
    previous_chunk_id = previous.results[0].chunk_id

    stored_file = next((tmp_path / "knowledge").iterdir())
    stored_file.write_bytes(b"activation-failure-generation must remain hidden")
    async with sessions() as session:
        replacement = IngestionJobModel(document_id=str(accepted.document.id), state="queued")
        session.add(replacement)
        await session.commit()
        await session.refresh(replacement)
        replacement_job_id = UUID(replacement.id)

    failing_repository = FailingActivationRepository(sessions)
    failing_service = KnowledgeService(
        repository=failing_repository,
        vector_store=vector_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    worker = LocalIngestionWorker(failing_service)
    await worker.start()
    try:
        assert (
            await wait_for_repository_job(
                failing_repository, replacement_job_id, {"completed", "failed"}
            )
            == "failed"
        )
    finally:
        await worker.stop()

    assert failing_repository.activation_attempted
    assert failing_repository.staged_chunk_ids
    async with sessions() as session:
        staged_chunk_count = await session.scalar(
            select(func.count(ChunkModel.id)).where(
                ChunkModel.ingestion_job_id == str(replacement_job_id)
            )
        )
        staged_vector_count = await session.scalar(
            select(func.count(EmbeddingModel.id)).where(
                EmbeddingModel.chunk_id.in_(
                    [str(chunk_id) for chunk_id in failing_repository.staged_chunk_ids]
                )
            )
        )
    assert staged_chunk_count == 0
    assert staged_vector_count == 0

    preserved = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="previous-completed-generation", top_k=3, hybrid=True),
    )
    assert preserved.results[0].chunk_id == previous_chunk_id
    assert all("activation-failure-generation" not in item.content for item in preserved.results)

    stored_file.write_bytes(b"reingestion-after-activation-failure succeeds")
    async with sessions() as session:
        retry = IngestionJobModel(document_id=str(accepted.document.id), state="queued")
        session.add(retry)
        await session.commit()
        await session.refresh(retry)
        retry_job_id = UUID(retry.id)
    await service.process_job(retry_job_id)
    retried = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="reingestion-after-activation-failure", top_k=1),
    )
    assert retried.results[0].chunk_id != previous_chunk_id
    assert "reingestion-after-activation-failure" in retried.results[0].content
    await engine.dispose()


@pytest.mark.asyncio
async def test_activation_cleanup_never_rewrites_an_already_completed_job(tmp_path: Path) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'ambiguous-activation.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    embeddings = DeterministicEmbeddingProvider()
    repository = RaisingAfterActivationRepository(sessions)
    vector_store = SqlAlchemyVectorStore(sessions)
    service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    service.bind_enqueue(lambda _job_id: None)
    base = await service.create_base(
        KnowledgeBaseCreate(name="Activation acknowledgement", description="Regression corpus")
    )
    accepted = await service.queue_upload(
        base.id,
        "committed.txt",
        "text/plain",
        b"committed-activation-generation remains available",
    )

    with pytest.raises(RuntimeError, match="lost activation acknowledgement"):
        await service.process_job(accepted.ingestion_job.id)

    assert (await repository.get_job(accepted.ingestion_job.id)).state.value == "completed"
    result = await service.search(
        [base.id], KnowledgeSearchRequest(query="committed-activation-generation", top_k=1)
    )
    assert result.results[0].document == "committed.txt"
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_sqlite_workers_cannot_process_same_document_concurrently(
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'concurrent-jobs.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    repository = KnowledgeRepository(sessions)
    vector_store = SqlAlchemyVectorStore(sessions)
    stable_embeddings = DeterministicEmbeddingProvider()
    stable_service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=stable_embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    stable_service.bind_enqueue(lambda _job_id: None)
    base = await stable_service.create_base(
        KnowledgeBaseCreate(name="Concurrent jobs", description="Regression corpus")
    )
    accepted = await stable_service.queue_upload(
        base.id,
        "concurrent.txt",
        "text/plain",
        b"stable-generation remains visible during replacement",
    )
    await stable_service.process_job(accepted.ingestion_job.id)
    old_result = await stable_service.search(
        [base.id], KnowledgeSearchRequest(query="stable-generation", top_k=1)
    )
    old_chunk_id = old_result.results[0].chunk_id

    stored_file = next((tmp_path / "knowledge").iterdir())
    stored_file.write_bytes(b"single-winning-concurrent-generation becomes searchable")
    async with sessions() as session:
        first = IngestionJobModel(document_id=str(accepted.document.id), state="queued")
        second = IngestionJobModel(document_id=str(accepted.document.id), state="queued")
        session.add_all([first, second])
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)
        replacement_ids = [UUID(first.id), UUID(second.id)]

    blocking_embeddings = BlockingEmbeddingProvider()
    concurrent_service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=blocking_embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    worker = LocalIngestionWorker(concurrent_service, worker_count=2)
    await worker.start()
    try:
        await asyncio.wait_for(blocking_embeddings.entered.wait(), timeout=2)
        for _ in range(300):
            states = [(await repository.get_job(job_id)).state.value for job_id in replacement_ids]
            if "failed" in states or blocking_embeddings.max_active_calls > 1:
                break
            await asyncio.sleep(0.01)

        during = await stable_service.search(
            [base.id], KnowledgeSearchRequest(query="stable-generation", top_k=1, hybrid=True)
        )
        assert during.results[0].chunk_id == old_chunk_id
        blocking_embeddings.release.set()
        terminal_states = [
            await wait_for_repository_job(repository, job_id, {"completed", "failed"})
            for job_id in replacement_ids
        ]
    finally:
        blocking_embeddings.release.set()
        await worker.stop()

    assert blocking_embeddings.max_active_calls == 1
    assert sorted(terminal_states) == ["completed", "failed"]
    completed_job_id = replacement_ids[terminal_states.index("completed")]
    async with sessions() as session:
        active_generations = list(
            await session.scalars(
                select(ChunkModel.ingestion_job_id).where(
                    ChunkModel.document_id == str(accepted.document.id)
                )
            )
        )
    assert active_generations
    assert set(active_generations) == {str(completed_job_id)}
    assert (await repository.get_job(completed_job_id)).state.value == "completed"

    final = await stable_service.search(
        [base.id],
        KnowledgeSearchRequest(query="single-winning-concurrent-generation", top_k=1, hybrid=True),
    )
    assert final.results[0].chunk_id != old_chunk_id
    assert "single-winning-concurrent-generation" in final.results[0].content
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_dirty_generation_is_invisible_to_every_retrieval_boundary(
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'dirty-failed.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    repository = KnowledgeRepository(sessions)
    embeddings = DeterministicEmbeddingProvider()
    vector_store = SqlAlchemyVectorStore(sessions)
    service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    base = await repository.create_base(
        KnowledgeBaseCreate(name="Dirty failed data", description="Regression corpus"),
        embeddings.name,
        embeddings.model,
    )
    document, job = await repository.create_document_and_job(
        base.id,
        "dirty.txt",
        "upload://dirty.txt",
        "text/plain",
        1,
        tmp_path / "dirty.txt",
    )
    await repository.fail_job(job.id, "simulated cleanup failure")
    dirty_content = "dirty-failed-exclusive-token must never become evidence"
    dirty_vector = (await embeddings.embed([dirty_content]))[0]
    async with sessions() as session:
        dirty_chunk = ChunkModel(
            knowledge_base_id=str(base.id),
            document_id=str(document.id),
            ingestion_job_id=str(job.id),
            chunk_index=0,
            content=dirty_content,
            token_count=6,
            metadata_json="{}",
        )
        session.add(dirty_chunk)
        await session.flush()
        session.add(
            EmbeddingModel(
                chunk_id=dirty_chunk.id,
                provider=embeddings.name,
                model=embeddings.model,
                dimensions=len(dirty_vector),
                vector_json=json.dumps(dirty_vector),
                metadata_json="{}",
            )
        )
        await session.commit()
        dirty_chunk_id = UUID(dirty_chunk.id)

    assert await repository.list_chunk_candidates([base.id], None) == []
    assert await vector_store.search([base.id], dirty_vector, 5) == []
    semantic = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="dirty-failed-exclusive-token", top_k=5, hybrid=False),
    )
    hybrid = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="dirty-failed-exclusive-token", top_k=5, hybrid=True),
    )
    assert semantic.results == []
    assert hybrid.results == []
    assert await repository.hydrate_matches(
        [VectorMatch(chunk_id=dirty_chunk_id, score=1.0)]
    ) == []
    await engine.dispose()


def test_pgvector_search_query_requires_completed_generation() -> None:
    statement, params = PgVectorStore._build_search_query(
        knowledge_base_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        query_vector=[1.0, 0.0],
        top_k=3,
        filters=None,
    )
    sql = str(statement)
    assert "JOIN ingestion_jobs j ON j.id = c.ingestion_job_id" in sql
    assert "j.state = :completed_state" in sql
    assert "j.document_id = c.document_id" in sql
    assert params["completed_state"] == "completed"


@pytest.mark.asyncio
async def test_processing_generation_is_hidden_until_restart_recovery(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'staged-recovery.db').as_posix()}"
    engine, sessions = build_database(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = KnowledgeRepository(sessions)
    embeddings = DeterministicEmbeddingProvider()
    vector_store = SqlAlchemyVectorStore(sessions)
    service = KnowledgeService(
        repository=repository,
        vector_store=vector_store,
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    service.bind_enqueue(lambda _job_id: None)
    base = await service.create_base(
        KnowledgeBaseCreate(name="Crash recovery", description="Regression corpus")
    )
    accepted = await service.queue_upload(
        base.id,
        "crash.txt",
        "text/plain",
        b"restart-recovery-exclusive-token becomes visible only after activation",
    )
    document = await repository.mark_processing(accepted.ingestion_job.id)
    assert document is not None
    drafts = [
        ChunkDraft(
            index=0,
            content="restart-recovery-exclusive-token becomes visible only after activation",
            token_count=6,
            metadata={"format": "text"},
        )
    ]
    staged = await repository.stage_chunks(accepted.ingestion_job.id, document, drafts)
    vectors = await embeddings.embed([drafts[0].content])
    await vector_store.upsert(
        [
            EmbeddingVector(
                chunk_id=staged[0].id,
                vector=vectors[0],
                provider=embeddings.name,
                model=embeddings.model,
                metadata=staged[0].metadata,
            )
        ]
    )
    hidden = await service.search(
        [base.id],
        KnowledgeSearchRequest(query="restart-recovery-exclusive-token", top_k=3),
    )
    assert hidden.results == []
    await engine.dispose()

    restarted_engine, restarted_sessions = build_database(database_url)
    restarted_repository = KnowledgeRepository(restarted_sessions)
    restarted_service = KnowledgeService(
        repository=restarted_repository,
        vector_store=SqlAlchemyVectorStore(restarted_sessions),
        embeddings=embeddings,
        storage_root=tmp_path / "knowledge",
        max_file_bytes=1024,
    )
    assert await restarted_service.recover_jobs() == [accepted.ingestion_job.id]
    await restarted_service.process_job(accepted.ingestion_job.id)
    visible = await restarted_service.search(
        [base.id],
        KnowledgeSearchRequest(query="restart-recovery-exclusive-token", top_k=1),
    )
    assert visible.results[0].document == "crash.txt"
    assert visible.results[0].chunk_index == 0
    await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_jobs_for_one_document_do_not_process_concurrently(tmp_path: Path) -> None:
    engine, sessions = build_database(
        f"sqlite+aiosqlite:///{(tmp_path / 'duplicate-jobs.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = KnowledgeRepository(sessions)
    base = await repository.create_base(
        KnowledgeBaseCreate(name="Duplicate jobs", description="Regression corpus"),
        "local",
        "feature-hash-v1-256",
    )
    document, first_job = await repository.create_document_and_job(
        base.id,
        "duplicate.txt",
        "upload://duplicate.txt",
        "text/plain",
        4,
        tmp_path / "duplicate.txt",
    )
    async with sessions() as session:
        duplicate = IngestionJobModel(document_id=str(document.id), state="queued")
        session.add(duplicate)
        await session.commit()
        await session.refresh(duplicate)
        duplicate_id = UUID(duplicate.id)

    assert await repository.mark_processing(first_job.id) is not None
    assert await repository.mark_processing(duplicate_id) is None
    duplicate_view = await repository.get_job(duplicate_id)
    assert duplicate_view.state.value == "failed"
    assert "already processing" in str(duplicate_view.error)
    await repository.fail_job(first_job.id, "test cleanup")
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_chunk_visibility_migration_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "legacy-rag.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_bases (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                description TEXT NOT NULL,
                embedding_provider VARCHAR(80) NOT NULL,
                embedding_model VARCHAR(160) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE documents (
                id VARCHAR(36) PRIMARY KEY,
                knowledge_base_id VARCHAR(36) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                source VARCHAR(500) NOT NULL,
                mime_type VARCHAR(120) NOT NULL,
                size_bytes BIGINT NOT NULL,
                storage_path TEXT NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE ingestion_jobs (
                id VARCHAR(36) PRIMARY KEY,
                document_id VARCHAR(36) NOT NULL,
                state VARCHAR(20) NOT NULL,
                error TEXT,
                queued_at DATETIME NOT NULL,
                started_at DATETIME,
                completed_at DATETIME
            );
            CREATE TABLE chunks (
                id VARCHAR(36) PRIMARY KEY,
                knowledge_base_id VARCHAR(36) NOT NULL,
                document_id VARCHAR(36) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                UNIQUE (document_id, chunk_index)
            );
            INSERT INTO knowledge_bases VALUES (
                '00000000-0000-0000-0000-000000000001', 'Legacy', '', 'local',
                'feature-hash-v1-256', '2026-08-13 00:00:00'
            );
            INSERT INTO documents VALUES (
                '00000000-0000-0000-0000-000000000011',
                '00000000-0000-0000-0000-000000000001', 'completed.txt',
                'upload://completed.txt', 'text/plain', 1, 'completed.txt',
                '2026-08-13 00:00:00'
            );
            INSERT INTO documents VALUES (
                '00000000-0000-0000-0000-000000000012',
                '00000000-0000-0000-0000-000000000001', 'ambiguous.txt',
                'upload://ambiguous.txt', 'text/plain', 1, 'ambiguous.txt',
                '2026-08-13 00:00:00'
            );
            INSERT INTO ingestion_jobs VALUES (
                '00000000-0000-0000-0000-000000000021',
                '00000000-0000-0000-0000-000000000011', 'completed', NULL,
                '2026-08-13 00:00:00', '2026-08-13 00:00:01', '2026-08-13 00:00:02'
            );
            INSERT INTO ingestion_jobs VALUES (
                '00000000-0000-0000-0000-000000000022',
                '00000000-0000-0000-0000-000000000012', 'completed', NULL,
                '2026-08-13 00:00:00', '2026-08-13 00:00:01', '2026-08-13 00:00:02'
            );
            INSERT INTO ingestion_jobs VALUES (
                '00000000-0000-0000-0000-000000000023',
                '00000000-0000-0000-0000-000000000012', 'failed', 'legacy failure',
                '2026-08-13 00:01:00', '2026-08-13 00:01:01', '2026-08-13 00:01:02'
            );
            INSERT INTO chunks VALUES (
                '00000000-0000-0000-0000-000000000031',
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000011', 0,
                'completed legacy evidence', 3, '{}', '2026-08-13 00:00:02'
            );
            INSERT INTO chunks VALUES (
                '00000000-0000-0000-0000-000000000032',
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000012', 0,
                'ambiguous failed replacement', 3, '{}', '2026-08-13 00:01:02'
            );
            """
        )

    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    app = create_app(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        pass

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
        }
        generations = dict(
            connection.execute(
                "SELECT document_id, ingestion_job_id FROM chunks"
            ).fetchall()
        )
    assert "ingestion_job_id" in columns
    assert generations["00000000-0000-0000-0000-000000000011"] == (
        "00000000-0000-0000-0000-000000000021"
    )
    assert generations["00000000-0000-0000-0000-000000000012"] is None


@pytest.mark.asyncio
async def test_search_supports_top_k_metadata_filters_and_semantic_mode(
    client: AsyncClient,
) -> None:
    base = await create_base(client)
    base_id = str(base["id"])
    uploaded = await upload_fixture(client, base_id, "agent_studio.md", "text/markdown")
    await upload_fixture(client, base_id, "security_policy.txt", "text/plain")

    response = await client.post(
        f"/knowledge-bases/{base_id}/search",
        json={
            "query": "provider tests API key",
            "top_k": 1,
            "hybrid": False,
            "filters": {"document_id": uploaded["document"]["id"]},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == "semantic"
    assert len(body["results"]) == 1
    assert body["results"][0]["document"] == "agent_studio.md"
    assert body["results"][0]["document_id"] == uploaded["document"]["id"]
    assert body["results"][0]["chunk_id"]
    assert body["results"][0]["metadata"]["format"] == "markdown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type", "data", "expected_status"),
    [
        ("../escape.txt", "text/plain", b"safe text", 400),
        ("malware.exe", "application/octet-stream", b"MZ", 415),
        ("notes.txt", "application/pdf", b"safe text", 415),
        ("fake.pdf", "application/pdf", b"not a pdf", 400),
        ("binary.txt", "text/plain", b"hello\x00world", 400),
    ],
)
async def test_upload_security_validation(
    client: AsyncClient,
    filename: str,
    content_type: str,
    data: bytes,
    expected_status: int,
) -> None:
    base = await create_base(client, filename)
    response = await client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={"file": (filename, data, content_type)},
    )
    assert response.status_code == expected_status


def test_upload_size_limit_is_enforced_before_storage() -> None:
    with pytest.raises(KnowledgeValidationError, match="size limit"):
        _validate_upload("large.txt", "text/plain", b"12345", max_file_bytes=4)


@pytest.mark.asyncio
async def test_pdf_text_is_ingested_with_page_metadata(client: AsyncClient) -> None:
    base = await create_base(client, "PDF knowledge")
    response = await client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={"file": ("guide.pdf", _text_pdf(), "application/pdf")},
    )
    assert response.status_code == 202
    await wait_for_job(client, response.json()["ingestion_job"]["id"], "completed")
    search = await client.post(
        f"/knowledge-bases/{base['id']}/search",
        json={"query": "PDF citations page metadata", "top_k": 1},
    )
    result = search.json()["results"][0]
    assert result["document"] == "guide.pdf"
    assert result["metadata"]["page"] == 1

    agent = await client.post(
        "/agents",
        json={
            "name": "PDF Agent",
            "instructions": "Answer from the attached PDF.",
            "runtime_mode": "mock",
            "tools": ["knowledge_search"],
            "knowledge_base_ids": [base["id"]],
        },
    )
    run = await client.post(
        f"/agents/{agent.json()['id']}/runs",
        json={"input": "Where is PDF page metadata retained?"},
    )
    run_id = run.json()["id"]
    for _ in range(200):
        current = (await client.get(f"/runs/{run_id}")).json()
        if current["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    assert current["status"] == "completed"
    events = (await client.get(f"/runs/{run_id}/events")).json()
    tool_event = next(event for event in events if event["type"] == "tool.completed")
    assert tool_event["payload"]["result"]["results"][0]["metadata"]["page"] == 1


def _text_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 72 720 Td (Agent Studio PDF citations include page metadata.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_parser_crash_isolated_as_failed_ingestion_job(client: AsyncClient) -> None:
    base = await create_base(client)
    response = await client.post(
        f"/knowledge-bases/{base['id']}/documents",
        files={"file": ("broken.pdf", b"%PDF-1.7\ninvalid", "application/pdf")},
    )
    assert response.status_code == 202
    job = await wait_for_job(client, response.json()["ingestion_job"]["id"], "failed")
    assert "parser" in str(job["error"]).lower()
    assert (await client.get("/health")).json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_mock_agent_uses_knowledge_search_and_preserves_citations(
    client: AsyncClient,
) -> None:
    base = await create_base(client)
    base_id = str(base["id"])
    await upload_fixture(client, base_id, "agent_studio.md", "text/markdown")
    agent_response = await client.post(
        "/agents",
        json={
            "name": "Grounded Agent",
            "instructions": "Answer from attached knowledge.",
            "runtime_mode": "mock",
            "tools": ["knowledge_search"],
            "knowledge_base_ids": [base_id],
        },
    )
    assert agent_response.status_code == 201
    accepted = await client.post(
        f"/agents/{agent_response.json()['id']}/runs",
        json={"input": "What is Agent Studio's mission?"},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["id"]
    for _ in range(200):
        run = (await client.get(f"/runs/{run_id}")).json()
        if run["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    assert run["status"] == "completed"
    events = (await client.get(f"/runs/{run_id}/events")).json()
    tool_event = next(event for event in events if event["type"] == "tool.completed")
    assert tool_event["payload"]["tool"] == "knowledge_search"
    assert tool_event["payload"]["arguments"] == {
        "query": "What is Agent Studio's mission?",
        "top_k": 5,
    }
    citation = tool_event["payload"]["result"]["results"][0]
    assert citation["document"] == "agent_studio.md"
    assert citation["document_id"]
    assert citation["chunk_id"]
    assert citation["source"] == "upload://agent_studio.md"
    assert isinstance(citation["score"], float)
    assert events[-1]["type"] == "run.completed"


@pytest.mark.asyncio
async def test_agent_memory_and_knowledge_search_coexist(client: AsyncClient) -> None:
    base = await create_base(client, "Memory and RAG")
    base_id = str(base["id"])
    await upload_fixture(client, base_id, "agent_studio.md", "text/markdown")
    agent_response = await client.post(
        "/agents",
        json={
            "name": "Memory and Knowledge Agent",
            "instructions": "Use relevant memory and attached knowledge.",
            "runtime_mode": "mock",
            "tools": ["knowledge_search"],
            "knowledge_base_ids": [base_id],
            "memory_enabled": True,
        },
    )
    assert agent_response.status_code == 201
    agent_id = agent_response.json()["id"]

    async def run(input_text: str) -> tuple[dict[str, object], list[dict[str, object]]]:
        accepted = await client.post(f"/agents/{agent_id}/runs", json={"input": input_text})
        assert accepted.status_code == 202
        run_id = accepted.json()["id"]
        current: dict[str, object] = {}
        for _ in range(200):
            current = (await client.get(f"/runs/{run_id}")).json()
            if current["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.01)
        assert current["status"] == "completed"
        events = (await client.get(f"/runs/{run_id}/events")).json()
        return current, events

    _, first_events = await run("Remember that project codename is Atlas.")
    assert any(
        event["type"] == "tool.completed" and event["payload"]["tool"] == "knowledge_search"
        for event in first_events
    )
    assert any(event["type"] == "memory.written" for event in first_events)

    _, second_events = await run(
        "Remember that project codename is Atlas and deployment region is east."
    )
    event_types = [event["type"] for event in second_events]
    knowledge_result = next(
        event
        for event in second_events
        if event["type"] == "tool.completed"
        and event["payload"]["tool"] == "knowledge_search"
    )
    assert knowledge_result["payload"]["result"]["results"][0]["chunk_id"]
    assert event_types.index("memory.retrieved") < event_types.index("tool.selected")
    assert event_types.index("tool.selected") < event_types.index("tool.completed")
    assert event_types.index("tool.completed") < event_types.index("memory.written")
    assert event_types.index("memory.written") < event_types.index("run.completed")


def test_knowledge_search_tool_declares_hardened_contract() -> None:
    tool = KnowledgeSearchTool(cast(KnowledgeService, object())).as_tool()
    definition = tool.definition

    assert definition.input_schema is KnowledgeSearchInput
    assert definition.output_schema is KnowledgeSearchResponse
    assert definition.permissions == frozenset({"knowledge:read"})
    assert definition.timeout_seconds == 15.0
    assert definition.output_limit == 100_000
    assert "knowledge_base_ids" not in definition.input_schema.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_knowledge_search_tool_permission_and_scope_failures_are_classified() -> None:
    tool = KnowledgeSearchTool(cast(KnowledgeService, object())).as_tool()
    executor = ToolExecutor(ToolRegistry([tool]))
    call = ToolCall(name="knowledge_search", arguments={"query": "evidence", "top_k": 1})

    with pytest.raises(ToolPermissionError, match="not granted"):
        await executor.execute(call, set())
    with pytest.raises(ToolExecutionError, match="no knowledge bases"):
        await executor.execute(call, {"knowledge:read"})


@pytest.mark.asyncio
async def test_worker_recovers_queued_and_processing_jobs_without_duplicate_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "recovery.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    storage_path = tmp_path / "knowledge"
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "embedding_provider", "local")

    first_app = create_app(database_url, str(storage_path))
    async with first_app.router.lifespan_context(first_app):
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as http:
            base = await create_base(http, "Recovery benchmark")
            base_id = str(base["id"])
            queued = await upload_fixture(http, base_id, "agent_studio.md", "text/markdown")
            processing = await upload_fixture(http, base_id, "security_policy.txt", "text/plain")

    job_states = {
        str(queued["ingestion_job"]["id"]): "queued",
        str(processing["ingestion_job"]["id"]): "processing",
    }
    document_ids = [
        str(queued["document"]["id"]),
        str(processing["document"]["id"]),
    ]
    with sqlite3.connect(database_path) as connection:
        before = {
            document_id: connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            for document_id in document_ids
        }
        for job_id, state in job_states.items():
            connection.execute(
                "UPDATE ingestion_jobs SET state = ?, completed_at = NULL WHERE id = ?",
                (state, job_id),
            )
        connection.commit()

    second_app = create_app(database_url, str(storage_path))
    async with second_app.router.lifespan_context(second_app):
        async with AsyncClient(
            transport=ASGITransport(app=second_app), base_url="http://test"
        ) as http:
            for job_id in job_states:
                await wait_for_job(http, job_id, "completed")

    with sqlite3.connect(database_path) as connection:
        after = {
            document_id: connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
            for document_id in document_ids
        }
    assert before == after
    assert all(count > 0 for count in after.values())


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected_by_http_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "knowledge_max_file_bytes", 4)
    app = create_app(
        f"sqlite+aiosqlite:///{(tmp_path / 'size.db').as_posix()}",
        str(tmp_path / "knowledge"),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            base = await create_base(http, "Size limit")
            response = await http.post(
                f"/knowledge-bases/{base['id']}/documents",
                files={"file": ("large.txt", b"12345", "text/plain")},
            )
    assert response.status_code == 413
