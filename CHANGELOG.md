# Changelog

## v1.0.0

### Runtime and tools

- Added the application-owned bounded AgentLoop, deterministic Mock path, Agents SDK adapter, typed lifecycle events, cancellation, retry, timeout, and safe Calculator execution.

### Knowledge, Memory, and persistence

- Added asynchronous document ingestion, local embeddings, semantic/lexical/hybrid retrieval, completed-only replacement consistency, inspectable citations, and PostgreSQL/pgvector (`vector(256)` plus HNSW).
- Added policy-controlled, Agent-scoped durable Memory with ranking, dedupe, expiration, deletion, and deterministic SQLite/PostgreSQL transaction behavior.

### Observability and Evaluation

- Added persisted Run/RunEvent lineage, trace filters, redaction, usage/latency projections, dashboard telemetry, and deterministic PASS/FAIL/ERROR Evaluation over isolated real Runs.

### Providers, security, and delivery

- Added first-class, real-tested DeepSeek Chat Completions support and an implemented but live-NOT-TESTED OpenAI Responses/embeddings boundary.
- Added bounded uploads, untrusted-context separation, tool/resource limits, safe error handling, loopback defaults, non-root/read-only containers, runtime secrets, and fail-closed readiness.
- Added the production-like Docker runtime plus GitHub Actions gates for Backend, PostgreSQL, Frontend, Playwright, Docker, Reliability, Performance, and Delivery Validation.

### Known limitations

Authentication, RBAC, multi-tenancy, distributed workers, Kubernetes, public deployment, backup automation, and production SLA are not implemented. Real OpenAI and internet production load are not tested. See [docs/V1_STATUS.md](docs/V1_STATUS.md).
