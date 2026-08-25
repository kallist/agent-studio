# Agent Studio resume material

Use only claims that match the final release evidence. Do not replace “production-like” with “production-ready,” and do not describe OpenAI as live-tested.

## A. Short positioning

Observable AI Agent lifecycle platform with bounded execution, RAG, durable Memory, tracing, and deterministic Evaluation.

## B. Project description

Built a production-like local AI Agent development platform that makes tool execution, retrieval, Memory, traces, and Evaluation inspectable and reproducible. The system combines a Next.js Studio, FastAPI application-owned AgentLoop, PostgreSQL/pgvector, real-tested DeepSeek integration, secure Docker runtime, and automated reliability/performance gates.

## C. Three resume bullets

- Designed an application-owned bounded AgentLoop that decouples step limits, retries, timeout, cancellation, tool permissions, terminal state, and audit events from the provider SDK; validated the same contracts through deterministic Mock and real DeepSeek paths.
- Implemented completed-only RAG and Agent-scoped durable Memory on SQLite/PostgreSQL, including `vector(256)` HNSW retrieval, citation provenance, dedupe, expiration, and row-lock transaction ordering that prevents partial ingestion and concurrent-write races.
- Built persisted Run/RunEvent observability and isolated PASS/FAIL/ERROR Evaluation, then packaged the stack as non-root production images with seven independent CI jobs plus Delivery Validation for real PostgreSQL, browser, recovery, and synthetic p50/p95 regressions.

## D. Five resume bullets

- Built a Next.js/FastAPI Agent lifecycle workbench covering definition, execution, safe tools, RAG, Memory, traces, and deterministic Evaluation rather than a chatbot-only UI.
- Kept the Agents SDK behind an adapter while application code owns execution policy, capture-only tool calls, persistence, citations, Memory, and security boundaries.
- Implemented asynchronous, bounded txt/Markdown/PDF ingestion with completed-only generation visibility, semantic/lexical/hybrid search, pgvector HNSW indexing, and server-owned citation provenance.
- Added Agent-scoped durable Memory with explicit write/retrieval/expiration/delete policy, deterministic disable/finalization ordering, SQLite serialization, and PostgreSQL `SELECT FOR UPDATE` concurrency semantics.
- Delivered a production-like Docker runtime and GitHub Actions quality system spanning backend, real PostgreSQL/pgvector, frontend, 18 default Playwright flows, Docker, reliability, performance, and fresh-stack Delivery Validation.

## E. Technology stack

Python 3.12, FastAPI, Pydantic, SQLAlchemy async, pytest, OpenAI Agents SDK adapter, DeepSeek Chat Completions, Next.js 16, React 19, TypeScript strict, Tailwind CSS, Vitest, Playwright, PostgreSQL 17, pgvector 0.8.6, Docker Compose, GitHub Actions.

## F. Hard problems solved

- Preserving application control while still using a provider SDK.
- Preventing failed or in-progress re-ingestion generations from leaking into retrieval/citations.
- Making durable Memory policy auditable and concurrency outcomes deterministic across two databases.
- Keeping one persisted execution lineage for live traces, dashboards, and Evaluation without duplicate events.
- Separating real-provider secrets and nondeterministic validation from default offline CI.

## G. Interview highlights

Explain the AgentLoop boundary, ToolExecutor ownership, completed-only RAG activation, Memory row locking, Run/RunEvent lineage, Evaluation-owned Agent snapshots, DeepSeek provider identity, and production-like Docker trust boundaries.

## H. Quantifiable validation

- 232 backend tests collected for the v1 candidate; the default offline selection passed 206 tests with 26 provider/PostgreSQL/performance cases explicitly deselected.
- 18 deterministic default Playwright scenarios plus four explicit DeepSeek and four explicit OpenAI browser scenarios; OpenAI scenarios are present but live NOT TESTED.
- Seven independent CI jobs and one Delivery workflow.
- Real PostgreSQL 17 / pgvector 0.8.6 catalog and workflow integration, including 256-dimensional vectors and HNSW.
- Synthetic baseline records throughput plus p50/p95 for nine API, Agent, RAG, Memory, trace, Evaluation, and concurrency scenarios.
- Current timings are machine-dependent and must be copied from the final v1 PR evidence, not guessed here.

## I. Claims not to make

Do not claim enterprise production readiness, authentication/RBAC/multi-tenancy, Kubernetes, distributed workers, public deployment, high availability, zero downtime, production SLA, massive concurrency, or live OpenAI validation.

## Role-focused variants

### AI Application Engineer

Built an end-to-end Agent lifecycle product that turns runtime decisions, RAG citations, Memory, and Evaluation into inspectable user workflows, with deterministic demos and a real-tested DeepSeek option.

### Backend / Agent Engineer

Designed bounded AgentLoop, ToolExecutor, persistence, pgvector retrieval, row-locked Memory, ordered events, and isolated Evaluation behind typed ports, then proved them through offline and real-database integration suites.

### AI Product / Solution Engineer

Converted difficult Agent debugging problems into a coherent Studio experience and repeatable demo, while keeping claims, provider status, operational limitations, and validation evidence explicit.
