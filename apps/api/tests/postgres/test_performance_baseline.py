from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.memory.keys import normalized_memory_key
from app.memory.policy import MemoryPolicy
from app.memory.retriever import MemoryRetriever
from app.memory.store import SqlAlchemyMemoryStore
from app.persistence.models import MemoryModel

pytestmark = [pytest.mark.postgresql, pytest.mark.performance, pytest.mark.asyncio]

ROOT = Path(__file__).resolve().parents[4]
BASELINE_PATH = ROOT / "docs" / "performance-baseline.json"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _scenario(samples: list[float], *, count: int, failures: int = 0) -> dict[str, Any]:
    total_ms = sum(samples)
    return {
        "count": count,
        "duration_ms": round(total_ms, 3),
        "throughput_per_s": round(count / max(total_ms / 1000, 0.000001), 3),
        "p50_ms": round(_percentile(samples, 0.50), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "failure_count": failures,
    }


def _git_sha() -> str:
    configured = os.getenv("GITHUB_SHA")
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


async def _timed(awaitable: Any) -> tuple[Any, float]:
    started = perf_counter()
    result = await awaitable
    return result, (perf_counter() - started) * 1000


async def _wait_for_terminal(client: AsyncClient, run_id: str) -> dict[str, Any]:
    async with asyncio.timeout(15):
        while True:
            response = await client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            run = response.json()
            if run["status"] in TERMINAL_STATUSES:
                return run
            await asyncio.sleep(0.01)


async def _calculator_run(
    client: AsyncClient, agent_id: str
) -> tuple[dict[str, Any], float]:
    started = perf_counter()
    accepted = await client.post(
        f"/agents/{agent_id}/runs",
        json={"input": "Calculate 128 * 37 + 456"},
    )
    assert accepted.status_code == 202
    run = await _wait_for_terminal(client, accepted.json()["id"])
    return run, (perf_counter() - started) * 1000


async def _wait_for_ingestion(client: AsyncClient, job_id: str) -> dict[str, Any]:
    async with asyncio.timeout(90):
        while True:
            response = await client.get(f"/ingestion-jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()
            if job["state"] in {"completed", "failed"}:
                return job
            await asyncio.sleep(0.02)


async def _wait_for_evaluation(client: AsyncClient, run_id: str) -> dict[str, Any]:
    async with asyncio.timeout(90):
        while True:
            response = await client.get(f"/evaluation-runs/{run_id}")
            assert response.status_code == 200
            evaluation = response.json()
            if evaluation["status"] in TERMINAL_STATUSES:
                return evaluation
            await asyncio.sleep(0.02)


def _compare_with_baseline(
    scenarios: dict[str, dict[str, Any]], baseline: dict[str, Any]
) -> tuple[list[str], list[str]]:
    regressions: list[str] = []
    notices: list[str] = []
    catastrophic_multiplier = float(baseline["policy"]["catastrophic_multiplier"])
    noisy_multiplier = float(baseline["policy"]["report_only_multiplier"])
    for name, expected in baseline["scenarios"].items():
        actual = scenarios[name]
        expected_p95 = float(expected["p95_ms"])
        actual_p95 = float(actual["p95_ms"])
        if actual_p95 > expected_p95 * catastrophic_multiplier:
            regressions.append(
                f"{name} p95 {actual_p95}ms exceeds catastrophic limit "
                f"{expected_p95 * catastrophic_multiplier}ms"
            )
        elif actual_p95 > expected_p95 * noisy_multiplier:
            notices.append(f"{name} p95 increased beyond the report-only band")

        expected_throughput = float(expected.get("throughput_per_s", 0))
        actual_throughput = float(actual.get("throughput_per_s", 0))
        if (
            expected_throughput
            and actual_throughput < expected_throughput / catastrophic_multiplier
        ):
            regressions.append(
                f"{name} throughput {actual_throughput}/s is below catastrophic floor "
                f"{expected_throughput / catastrophic_multiplier}/s"
            )
    return regressions, notices


async def test_deterministic_postgresql_performance_baseline(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    client = postgres_client
    scenarios: dict[str, dict[str, Any]] = {}

    # Warm imports, the database connection, and the request path before measurements.
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/agents")).status_code == 200

    api_samples: list[float] = []
    for index in range(30):
        request = client.get("/health" if index % 2 == 0 else "/agents")
        response, elapsed_ms = await _timed(request)
        assert response.status_code == 200
        api_samples.append(elapsed_ms)
    scenarios["api_basic"] = _scenario(api_samples, count=len(api_samples))

    agent_response = await client.post(
        "/agents",
        json={
            "name": "Performance Calculator",
            "instructions": "Use the calculator deterministically.",
            "runtime_mode": "mock",
            "tools": ["calculator"],
        },
    )
    assert agent_response.status_code == 201
    calculator_agent_id = agent_response.json()["id"]

    sequential_samples: list[float] = []
    sequential_run_ids: list[str] = []
    for _ in range(20):
        run, elapsed_ms = await _calculator_run(client, calculator_agent_id)
        assert run["status"] == "completed" and run["output"] == "5192"
        sequential_run_ids.append(run["id"])
        sequential_samples.append(elapsed_ms)
    scenarios["agent_sequential"] = _scenario(
        sequential_samples, count=len(sequential_samples)
    )

    concurrent_started = perf_counter()
    concurrent_results = await asyncio.gather(
        *[_calculator_run(client, calculator_agent_id) for _ in range(10)]
    )
    concurrent_batch_ms = (perf_counter() - concurrent_started) * 1000
    concurrent_failures = sum(
        run["status"] != "completed" or run["output"] != "5192"
        for run, _elapsed in concurrent_results
    )
    concurrent_samples = [elapsed for _run, elapsed in concurrent_results]
    concurrent_metric = _scenario(
        concurrent_samples, count=len(concurrent_samples), failures=concurrent_failures
    )
    concurrent_metric["duration_ms"] = round(concurrent_batch_ms, 3)
    concurrent_metric["throughput_per_s"] = round(
        len(concurrent_results) / max(concurrent_batch_ms / 1000, 0.000001), 3
    )
    scenarios["agent_concurrent"] = concurrent_metric
    assert concurrent_failures == 0

    corpus_paragraphs = [
        (
            f"Task13 synthetic paragraph {index} reliability retrieval marker-{index}. "
            + "bounded deterministic pgvector baseline content " * 28
        )
        for index in range(120)
    ]
    corpus = "\n\n".join(corpus_paragraphs).encode()
    base_response = await client.post(
        "/knowledge-bases",
        json={"name": "Performance Corpus", "description": "Synthetic Task 13 data"},
    )
    assert base_response.status_code == 201
    knowledge_base_id = base_response.json()["id"]
    ingest_started = perf_counter()
    upload = await client.post(
        f"/knowledge-bases/{knowledge_base_id}/documents",
        files={"file": ("task13-performance.md", corpus, "text/markdown")},
    )
    assert upload.status_code == 202
    ingestion = await _wait_for_ingestion(
        client, upload.json()["ingestion_job"]["id"]
    )
    ingestion_ms = (perf_counter() - ingest_started) * 1000
    assert ingestion["state"] == "completed", ingestion
    ingest_metric = _scenario([ingestion_ms], count=120)
    ingest_metric["corpus_chunks_target"] = 120
    scenarios["rag_ingestion"] = ingest_metric

    retrieval_samples: dict[str, list[float]] = {"semantic": [], "hybrid": []}
    for mode, hybrid in (("semantic", False), ("hybrid", True)):
        for index in range(25):
            response, elapsed_ms = await _timed(
                client.post(
                    f"/knowledge-bases/{knowledge_base_id}/search",
                    json={
                        "query": f"reliability retrieval marker-{index % 10}",
                        "top_k": 3,
                        "hybrid": hybrid,
                    },
                )
            )
            assert response.status_code == 200
            assert response.json()["results"]
            retrieval_samples[mode].append(elapsed_ms)
        scenarios[f"rag_{mode}"] = _scenario(
            retrieval_samples[mode], count=len(retrieval_samples[mode])
        )

    memory_agent = (
        await client.post(
            "/agents",
            json={
                "name": "Performance Memory",
                "instructions": "Use memory as data.",
                "runtime_mode": "mock",
                "tools": [],
            },
        )
    ).json()
    memory_agent_id = UUID(memory_agent["id"])
    now = datetime.now(UTC)
    sessions = postgres_app.state.database_sessions
    async with sessions() as session:
        session.add_all(
            [
                MemoryModel(
                    id=str(uuid4()),
                    agent_id=str(memory_agent_id),
                    kind="long_term",
                    content=f"Project codename Task13 memory fact {index}",
                    normalized_key=normalized_memory_key(
                        f"Project codename Task13 memory fact {index}"
                    ),
                    importance=0.7,
                    created_at=now - timedelta(minutes=index),
                    expires_at=now + timedelta(days=180),
                    metadata_json="{}",
                )
                for index in range(500)
            ]
        )
        await session.commit()
    retriever = MemoryRetriever(SqlAlchemyMemoryStore(sessions), MemoryPolicy())
    memory_samples: list[float] = []
    for _ in range(20):
        matches, elapsed_ms = await _timed(
            retriever.retrieve(memory_agent_id, "What is the Task13 project codename?")
        )
        assert matches
        memory_samples.append(elapsed_ms)
    memory_metric = _scenario(memory_samples, count=len(memory_samples))
    memory_metric["record_count"] = 500
    scenarios["memory_retrieval"] = memory_metric

    trace_samples: list[float] = []
    trace_run_id = sequential_run_ids[0]
    for _ in range(25):
        response, elapsed_ms = await _timed(
            client.get(f"/runs/{trace_run_id}/observability")
        )
        assert response.status_code == 200
        assert response.json()["event_count"] >= 10
        trace_samples.append(elapsed_ms)
    scenarios["trace_read"] = _scenario(trace_samples, count=len(trace_samples))

    cases = [
        {
            "name": f"Performance case {index}",
            "input": "Calculate 128 * 37 + 456",
            "graders": [
                {"type": "run_status"},
                {"type": "exact_match", "value": "5192"},
                {"type": "tool_selected", "tool_name": "calculator"},
            ],
        }
        for index in range(20)
    ]
    suite_response = await client.post(
        "/evaluation-suites",
        json={
            "name": "Task 13 Performance Evaluation",
            "agent_id": calculator_agent_id,
            "cases": cases,
        },
    )
    assert suite_response.status_code == 201, suite_response.text
    evaluation_started = perf_counter()
    evaluation_response = await client.post(
        f"/evaluation-suites/{suite_response.json()['id']}/runs",
        headers={"Idempotency-Key": "task13-performance-evaluation"},
    )
    assert evaluation_response.status_code == 202
    evaluation = await _wait_for_evaluation(client, evaluation_response.json()["id"])
    evaluation_ms = (perf_counter() - evaluation_started) * 1000
    assert evaluation["status"] == "completed"
    assert evaluation["completed_cases"] == 20
    assert evaluation["error_cases"] == 0
    evaluation_metric = _scenario([evaluation_ms], count=20)
    evaluation_metric["case_count"] = 20
    scenarios["evaluation"] = evaluation_metric

    engine = sessions.kw["bind"]
    checked_out = engine.sync_engine.pool.checkedout()
    assert checked_out <= 1

    async with sessions() as session:
        postgres_version = str(await session.scalar(text("SHOW server_version")))
        pgvector_version = str(
            await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        )

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    regressions, notices = _compare_with_baseline(scenarios, baseline)
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "postgresql": postgres_version,
            "pgvector": pgvector_version,
        },
        "policy": baseline["policy"],
        "scenarios": scenarios,
        "report_only_notices": notices,
        "catastrophic_regressions": regressions,
        "connection_pool_checked_out_after_suite": checked_out,
    }
    output_path = Path(
        os.getenv(
            "PERFORMANCE_OUTPUT",
            str(Path(os.getenv("PYTEST_TMPDIR", ".pytest-tmp")) / "performance-summary.json"),
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(
        output_path.write_text,
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))

    assert not regressions, "; ".join(regressions)
    assert sys.version_info[:2] == (3, 12)
