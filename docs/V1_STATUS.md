# Agent Studio v1 source-of-truth matrix

This document is the claim boundary for v1. `IMPLEMENTED` means code exists; `TESTED` means an automated or explicitly recorded real validation exercises that behavior. A catalog entry, configuration field, or compiled SQL statement alone is not validation.

| Feature | Status | Real validation | Default / optional | Known limitation | Primary source |
|---|---|---|---|---|---|
| Application-owned `AgentLoop` | IMPLEMENTED · TESTED | Offline runtime, timeout, retry, cancellation, and reliability tests | Default | Single Agent per Run; no multi-agent orchestration | `runtime/engine.py`, `test_agent_loop.py` |
| Calculator and tool boundary | IMPLEMENTED · TESTED | Unit, API, Playwright, Docker Delivery | Default | Calculator is the only general demo tool | `tools/`, `test_tools.py` |
| Knowledge ingestion and RAG | IMPLEMENTED · TESTED | SQLite tests, Playwright, real PostgreSQL/pgvector, Docker Delivery | Optional per Agent | txt/Markdown/text-extractable PDF only; local worker | `RAG_DESIGN.md` |
| PostgreSQL + pgvector | IMPLEMENTED · TESTED | PostgreSQL 17, pgvector 0.8.6, `vector(256)`, HNSW catalog/data/query tests | Docker default | Managed PostgreSQL NOT TESTED | `POSTGRESQL_PGVECTOR.md` |
| SQLite persistence | IMPLEMENTED · TESTED | Offline backend and E2E | Host-development default | Explicit temporary/local fallback | `DEVELOPMENT.md` |
| Durable Memory | IMPLEMENTED · TESTED | Policy/ranking/dedupe tests plus real row-lock transaction interleavings | Enabled per Agent | Agent-scoped; no user/tenant authorization | `MEMORY_DESIGN.md` |
| Run observability | IMPLEMENTED · TESTED | Persisted Run/RunEvent aggregation, redaction, API, UI, E2E | Default | No OpenTelemetry export or distributed tracing | `OBSERVABILITY_DESIGN.md` |
| Deterministic Evaluation | IMPLEMENTED · TESTED | PASS/FAIL/ERROR, isolated real Runs, RAG/Memory lineage, UI/E2E | Optional | No LLM-as-a-Judge or distributed workers | `EVALUATION_DESIGN.md` |
| Security hardening | IMPLEMENTED · TESTED | Trust-boundary, resource-limit, redaction, XSS, upload, SSE, workflow tests | Default | No Auth/RBAC/multi-tenancy/global rate limit | `SECURITY_DESIGN.md` |
| Mock provider | IMPLEMENTED · TESTED | Full default backend, browser, Docker, CI path | Default | Deterministic behavior; usage is N/A | `MODEL_PROVIDERS.md` |
| DeepSeek provider | IMPLEMENTED · REAL TESTED | Stream, usage, Calculator, RAG, Memory, Evaluation, browser; protected manual CI workflow | Optional | Billable/nondeterministic; not a merge gate | `MODEL_PROVIDERS.md` |
| OpenAI Responses provider | IMPLEMENTED · LIVE NOT TESTED | Offline contracts and adapter tests only | Optional | Real OpenAI Responses NOT TESTED | `OPENAI_INTEGRATION.md` |
| OpenAI embeddings | IMPLEMENTED · LIVE NOT TESTED | Deterministic adapter/contract tests only | Optional | Real embeddings and OpenAI + pgvector NOT TESTED | `OPENAI_INTEGRATION.md` |
| Production-like Docker runtime | IMPLEMENTED · TESTED | Build, non-root images, cold/warm start, health, persistence/recovery, container E2E | Recommended | One API process; local loopback only | `CONTAINER_RUNTIME.md` |
| CI and Delivery Validation | IMPLEMENTED · TESTED | Successful main CI and Delivery runs for the v1 base | Automatic | No image publication or public deployment | `CI_RELIABILITY_PERFORMANCE.md` |
| Reliability regression suite | IMPLEMENTED · TESTED | Bounded failure/restart/concurrency scenarios | CI | Not high availability or full chaos engineering | `CI_RELIABILITY_PERFORMANCE.md` |
| Performance baseline | IMPLEMENTED · TESTED | Synthetic PostgreSQL/pgvector p50/p95/throughput scenarios | CI | Not capacity certification or production SLA | `performance-baseline.json` |

## Unified limitations

| Capability | v1 status |
|---|---|
| Authentication / authorization / RBAC / multi-tenancy | NOT IMPLEMENTED |
| Global rate limiting | NOT IMPLEMENTED |
| Horizontal or multiprocess API | NOT TESTED |
| Distributed ingestion/evaluation workers | NOT IMPLEMENTED / NOT TESTED |
| Kubernetes, public TLS/ingress, automatic public deployment | NOT IMPLEMENTED |
| Managed PostgreSQL | NOT TESTED |
| Automated backup/restore | NOT IMPLEMENTED |
| Cloud secret manager | NOT IMPLEMENTED |
| Real OpenAI Responses / embeddings / OpenAI + pgvector | NOT TESTED |
| Internet production load | NOT TESTED |
| Full chaos engineering / high availability / zero-downtime / SLA | NOT IMPLEMENTED / NOT CLAIMED |

This matrix must be updated whenever a release claim changes. Historical development notes do not override it.
