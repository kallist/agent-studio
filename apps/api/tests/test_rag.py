from __future__ import annotations

import asyncio
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.domain.contracts import KnowledgeSearchResponse, ToolCall
from app.domain.errors import KnowledgeValidationError, ToolExecutionError, ToolPermissionError
from app.knowledge.service import KnowledgeService, _validate_upload
from app.main import create_app
from app.persistence.database import settings
from app.tools.knowledge_search import KnowledgeSearchInput, KnowledgeSearchTool
from app.tools.registry import ToolExecutor, ToolRegistry

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "rag"


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


async def wait_for_job(
    client: AsyncClient, job_id: str, expected: str
) -> dict[str, object]:
    for _ in range(200):
        response = await client.get(f"/ingestion-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["state"] in {"completed", "failed"}:
            assert job["state"] == expected
            return job
        await asyncio.sleep(0.01)
    pytest.fail("ingestion did not reach a terminal state")


@pytest.mark.asyncio
async def test_rag_benchmark_recalls_expected_chunk_with_citations(client: AsyncClient) -> None:
    base = await create_base(client)
    base_id = str(base["id"])
    await upload_fixture(client, base_id, "agent_studio.md", "text/markdown")
    await upload_fixture(client, base_id, "security_policy.txt", "text/plain")

    benchmark = json.loads((FIXTURES / "benchmark.json").read_text(encoding="utf-8"))
    for case in benchmark["cases"]:
        response = await client.post(
            f"/knowledge-bases/{base_id}/search",
            json={"query": case["question"], "top_k": 3, "hybrid": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["algorithm"] == "hybrid"
        assert body["results"]
        relevant = [
            result
            for result in body["results"]
            if result["document"] == case["expected_document"]
            and case["expected_phrase"].lower() in result["content"].lower()
        ]
        assert relevant, case["question"]
        assert relevant[0]["source"].startswith("upload://")
        assert relevant[0]["chunk_id"]
        assert isinstance(relevant[0]["score"], float)


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
            processing = await upload_fixture(
                http, base_id, "security_policy.txt", "text/plain"
            )

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
