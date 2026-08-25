from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.domain.contracts import EmbeddingVector, KnowledgeBaseCreate
from app.domain.errors import KnowledgeValidationError
from app.knowledge.embeddings import DeterministicEmbeddingProvider
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.service import KnowledgeService
from app.knowledge.vector_store import PgVectorStore, _cosine
from app.persistence.database import build_database
from app.persistence.models import EmbeddingModel, IngestionJobModel

pytestmark = [pytest.mark.postgresql, pytest.mark.reliability, pytest.mark.asyncio]


async def _wait_for_job(client: AsyncClient, job_id: str) -> dict[str, object]:
    for _ in range(300):
        response = await client.get(f"/ingestion-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"completed", "failed"}:
            return job
        await asyncio.sleep(0.01)
    pytest.fail("PostgreSQL ingestion job did not reach a terminal state.")


async def _wait_for_run(client: AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(300):
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.01)
    pytest.fail("PostgreSQL-backed Run did not reach a terminal state.")


async def test_real_postgresql_schema_extension_vector_dimension_and_index(
    postgres_app: FastAPI,
    postgres_database_url: str,
) -> None:
    await postgres_app.state.knowledge_service._vector_store.initialize()
    engine, _ = build_database(postgres_database_url)
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("SHOW server_version"))
            extension_version = await connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            isolation = await connection.scalar(text("SHOW transaction_isolation"))
            vector_type = await connection.scalar(
                text(
                    """
                    SELECT format_type(attribute.atttypid, attribute.atttypmod)
                    FROM pg_attribute AS attribute
                    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                    WHERE relation.relname = 'rag_vectors'
                      AND attribute.attname = 'embedding'
                      AND attribute.attnum > 0
                    """
                )
            )
            index_definition = await connection.scalar(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE tablename = 'rag_vectors'
                      AND indexname = 'ix_rag_vectors_embedding_hnsw'
                    """
                )
            )
    finally:
        await engine.dispose()

    assert isinstance(version, str) and version
    assert isinstance(extension_version, str) and extension_version
    assert isolation == "read committed"
    assert vector_type == "vector(256)"
    assert index_definition is not None
    assert "hnsw" in str(index_definition).lower()
    assert "vector_cosine_ops" in str(index_definition).lower()


async def test_database_health_reports_real_postgresql_readiness(
    postgres_client: AsyncClient,
) -> None:
    response = await postgres_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_missing_pgvector_extension_permission_fails_startup_clearly(
    postgres_no_vector_database_url: str,
    tmp_path: Path,
) -> None:
    from app.main import create_app

    app = create_app(
        postgres_no_vector_database_url,
        knowledge_storage_path=str(tmp_path / "no-vector"),
    )
    with pytest.raises(RuntimeError, match="PostgreSQL pgvector initialization failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must fail when the configured role cannot create pgvector.")


async def test_pgvector_rejects_dimension_mismatch_before_database_write(
    postgres_app: FastAPI,
    postgres_database_url: str,
    tmp_path: Path,
) -> None:
    engine, sessions = build_database(postgres_database_url)
    store = PgVectorStore(sessions, dimensions=256)
    try:
        with pytest.raises(KnowledgeValidationError, match="256 dimensions"):
            await store.upsert(
                [
                    EmbeddingVector(
                        chunk_id=uuid4(),
                        vector=[0.0] * 255,
                        provider="local",
                        model="invalid-dimension-test",
                    )
                ]
            )

        repository = KnowledgeRepository(sessions)
        service = KnowledgeService(
            repository=repository,
            vector_store=store,
            embeddings=DeterministicEmbeddingProvider(dimensions=255),
            storage_root=tmp_path / "wrong-dimension",
            max_file_bytes=1_024,
        )
        queued: list[UUID] = []
        service.bind_enqueue(queued.append)
        base = await service.create_base(
            KnowledgeBaseCreate(name="Wrong dimensions", description="must fail safely")
        )
        accepted = await service.queue_upload(
            base.id,
            "wrong.txt",
            "text/plain",
            b"dimension mismatch must become a terminal ingestion failure",
        )
        assert queued == [accepted.ingestion_job.id]
        with pytest.raises(KnowledgeValidationError, match="256 dimensions"):
            await service.process_job(accepted.ingestion_job.id)
        assert (await service.get_job(accepted.ingestion_job.id)).state.value == "failed"
        async with sessions() as session:
            failed_state = await session.scalar(
                select(IngestionJobModel.state).where(
                    IngestionJobModel.id == str(accepted.ingestion_job.id)
                )
            )
            stored_vectors = await session.scalar(select(func.count(EmbeddingModel.id)))
        assert failed_state == "failed"
        assert stored_vectors == 0
    finally:
        await engine.dispose()


async def test_real_pgvector_write_semantic_hybrid_filters_and_parameterization(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    postgres_database_url: str,
) -> None:
    base_response = await postgres_client.post(
        "/knowledge-bases",
        json={"name": "PostgreSQL corpus", "description": "real pgvector integration"},
    )
    assert base_response.status_code == 201
    base = base_response.json()
    documents = [
        (
            "memory.txt",
            b"Agent Studio uses durable memory for cross-run facts.",
        ),
        (
            "transactions.txt",
            b"PostgreSQL supports transactional row locking.",
        ),
        (
            "distractor.txt",
            b"Garden soil benefits from seasonal compost and careful watering.",
        ),
    ]
    uploaded: dict[str, dict[str, object]] = {}
    for filename, data in documents:
        response = await postgres_client.post(
            f"/knowledge-bases/{base['id']}/documents",
            files={"file": (filename, data, "text/plain")},
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        uploaded[filename] = accepted
        job = await _wait_for_job(postgres_client, accepted["ingestion_job"]["id"])
        assert job["state"] == "completed", job

    semantic = await postgres_client.post(
        f"/knowledge-bases/{base['id']}/search",
        json={"query": "transactional row locking", "top_k": 2, "hybrid": False},
    )
    assert semantic.status_code == 200, semantic.text
    semantic_body = semantic.json()
    assert semantic_body["algorithm"] == "semantic"
    assert semantic_body["results"][0]["document"] == "transactions.txt"
    assert semantic_body["results"][0]["source"] == "upload://transactions.txt"

    hybrid = await postgres_client.post(
        f"/knowledge-bases/{base['id']}/search",
        json={
            "query": "durable memory cross-run facts",
            "top_k": 1,
            "hybrid": True,
            "filters": {
                "document_id": uploaded["memory.txt"]["document"]["id"],
                "source": "upload://memory.txt",
                "filename": "memory.txt",
            },
        },
    )
    assert hybrid.status_code == 200, hybrid.text
    hybrid_body = hybrid.json()
    assert hybrid_body["algorithm"] == "hybrid"
    assert hybrid_body["results"][0]["document_id"] == uploaded["memory.txt"]["document"]["id"]
    assert hybrid_body["results"][0]["chunk_id"]
    assert hybrid_body["results"][0]["score"] > 0
    embeddings = postgres_app.state.knowledge_service._embeddings
    query_vector = (await embeddings.embed(["transactional row locking"]))[0]
    result_vector = (await embeddings.embed([semantic_body["results"][0]["content"]]))[0]
    assert semantic_body["results"][0]["score"] == pytest.approx(
        _cosine(query_vector, result_vector), abs=1e-5
    )

    injection = await postgres_client.post(
        f"/knowledge-bases/{base['id']}/search",
        json={
            "query": "transactional row locking",
            "filters": {
                "source": "' OR 1=1 --",
                "filename": '"; DROP TABLE runs; --',
            },
        },
    )
    assert injection.status_code == 200
    assert injection.json()["results"] == []

    engine, _ = build_database(postgres_database_url)
    try:
        async with engine.connect() as connection:
            vector_rows = await connection.scalar(text("SELECT count(*) FROM rag_vectors"))
            dimensions = await connection.scalar(
                text("SELECT min(vector_dims(embedding)) FROM rag_vectors")
            )
            fallback_json_rows = await connection.scalar(
                text("SELECT count(*) FROM embeddings WHERE vector_json IS NOT NULL")
            )
            run_table = await connection.scalar(text("SELECT to_regclass('public.runs')"))
    finally:
        await engine.dispose()
    assert vector_rows == 3
    assert dimensions == 256
    assert fallback_json_rows == 0
    assert run_table == "runs"

    agent_response = await postgres_client.post(
        "/agents",
        json={
            "name": "PostgreSQL RAG Agent",
            "instructions": "Search attached knowledge and cite it.",
            "runtime_mode": "mock",
            "tools": ["knowledge_search"],
            "knowledge_base_ids": [base["id"]],
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    run_response = await postgres_client.post(
        f"/agents/{agent_response.json()['id']}/runs",
        json={"input": "What supports transactional row locking?"},
    )
    assert run_response.status_code == 202
    run = await _wait_for_run(postgres_client, run_response.json()["id"])
    assert run["status"] == "completed"
    assert "PostgreSQL supports transactional row locking" in str(run["output"])
    events = (await postgres_client.get(f"/runs/{run['id']}/events")).json()
    completed = next(event for event in events if event["type"] == "tool.completed")
    assert completed["payload"]["result"]["results"][0]["document"] == "transactions.txt"
    observability = (await postgres_client.get(f"/runs/{run['id']}/observability")).json()
    assert observability["tool_calls"] == {"total": 1, "succeeded": 1, "failed": 0}
    assert observability["event_statistics"]["tool.completed"] == 1
