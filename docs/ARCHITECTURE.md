# Agent Studio architecture

## Goals

Version 1 makes a real Agent Run observable from definition through Evaluation without turning the repository into a framework or a set of premature microservices. The Web and API applications are separate deployable boundaries; backend modules remain a modular monolith until scaling or ownership evidence justifies extraction.

## System context

```text
Browser
   ↓
Next.js Frontend
   ↓
FastAPI API
   ↓
Agent Runtime
   ├── LLM Provider
   ├── Tool Registry
   ├── Memory
   ├── Knowledge Retrieval
   └── Trace/Event System
   ↓
PostgreSQL / pgvector
```

The frontend never calls an LLM provider or a tool directly. FastAPI owns API contracts and is the future authentication boundary; authentication is not implemented in v1. `AgentService` coordinates application workflows. `AgentRuntime` executes a run behind a stable port. Persistence and retrieval are accessed through repositories/stores rather than ORM sessions in business code.

## Recommended repository structure

```text
agent-studio/
├── apps/
│   ├── web/                 # Next.js application, i18n dictionaries, Vitest and Playwright specs
│   └── api/                 # FastAPI modular monolith and pytest suites
├── docs/
│   ├── ADR/                 # Architecture decisions
│   ├── assets/              # Product screenshots referenced by documentation
│   └── demo/                # Deterministic demo fixtures
├── infra/                   # Local PostgreSQL/pgvector init assets
├── scripts/                 # Docker helper and CI validation scripts
├── tests/fixtures/          # Cross-application RAG benchmark and document fixtures
├── .github/workflows/       # CI, Delivery Validation, manual provider live validation
├── compose.yaml             # PostgreSQL/pgvector and application runtime
├── AGENTS.md
└── README.md
```

This keeps worktree changes easy to isolate by application without introducing a monorepo framework or shared-package build system before one is needed.

## Backend boundaries

The `apps/api` package is organized by responsibility, not by transport:

```text
app/
├── api/             # HTTP routes and dependency wiring
├── application/     # AgentService and use cases
├── domain/          # Entities, value objects, policies, ports
├── runtime/         # AgentRuntime implementations and SDK adapter
├── tools/           # Tool registry, validation, execution adapters
├── memory/          # Memory policies and store adapters
├── knowledge/       # Ingestion, retrieval, VectorStore adapters
├── evaluation/      # Suites, graders, worker, aggregation
├── observability/   # Run/RunEvent projection, redaction, metrics
└── persistence/     # SQLAlchemy models and repository adapters
```

These are module boundaries inside one FastAPI service, not separate services.

## Core contracts

### AgentService

Application-level coordinator. It validates requests, loads an agent definition, creates a run record, invokes `AgentRuntime`, persists events and terminal state, and returns a run view. It owns transaction and idempotency policy but not HTTP details or provider-specific calls.

### AgentRuntime

Port for executing an Agent Run. Its inputs and emitted events are application types. The real-provider adapter is `AgentsSdkRuntime`; deterministic tests and the default demo use `MockRuntime`. SDK result objects do not cross this boundary. Normal Agent Runs are not resumed after process restart; non-terminal persisted Runs are finalized with an explicit restart failure.

### LLMProvider

Port for model/provider selection, credentials, capabilities, and model invocation needed by a
runtime adapter. `OpenAIProvider` resolves the Responses model path, while `DeepSeekProvider`
resolves the OpenAI-compatible Chat Completions path through the same `AgentsSdkRuntime`.
`MockProvider` returns deterministic scripted outputs and tool requests without a network or API
key. Provider-specific clients, model shapes, capabilities, and settings stop at this resolver
boundary.

The OpenAI path uses a true streamed Responses request for each outer-loop step. The DeepSeek path
uses a streamed Chat Completions request with its own server-only key and official base URL. SDK
function callbacks only capture model-selected calls; `ToolExecutor` remains the sole business
execution boundary. Provider, API style, model, and aggregate usage are normalized into application
events, while raw SDK events, response objects, hosted sessions, and `previous_response_id` are not
persisted.

### ToolRegistry

Holds versioned tool definitions and resolves a tool by stable name. Definitions include input/output schema, permissions, timeout, side-effect classification, and output limits. Registry lookup performs no execution.

### ToolExecutor

Validates arguments, enforces approval and permissions, applies timeout/output limits, invokes the selected adapter, and records success or structured failure. HTTP tools must enforce SSRF defenses; file tools must enforce allowed roots and path traversal defenses.

### MemoryStore

Stores and retrieves application-owned conversation and agent memory. It keeps durable memory policy separate from the SDK's per-run/session continuation mechanics. Memory writes are explicit and auditable.

### KnowledgeStore

Owns source documents, chunks, ingestion status, provenance, and tenant/agent associations. It coordinates text extraction and embedding through ports but does not implement vector search itself.

### VectorStore

Port for upsert, delete, similarity search, metadata filters, and collection lifecycle. The first adapter uses pgvector; tests use an in-memory deterministic adapter. No pgvector operators appear in application or domain code.

### TraceStore

Persists the application event model used by the product UI: model request boundaries, tool calls, approvals, state transitions, errors, token/latency metadata, and correlation IDs. It may ingest SDK trace identifiers but does not make the OpenAI trace dashboard the product database.

### RunRepository

Persists run identity, agent version, status, timestamps, input/output references, failure details, and optimistic concurrency/idempotency data. It does not store arbitrary provider objects.

## Run flow

1. The frontend creates a run through FastAPI.
2. `AgentService` validates access, loads a versioned agent definition, and creates a pending run through `RunRepository`.
3. `AgentRuntime` starts a bounded application-owned `AgentLoop` with an `LLMProvider`, registered
   tools, explicit limits, and a cancellation token.
4. For each step, the loop builds a size-bounded `AgentContext`, asks the provider for one typed
   `AgentDecision`, validates the selected tool and duplicate-call policy, and either terminates or
   invokes `ToolExecutor`.
5. `ToolExecutor` validates input, permissions, timeout, output schema, and output size. Its
   `ToolResult` becomes the next step's observation.
6. Step/model/tool callbacks are normalized into application `AgentEvent` values and persisted
   before being published to the live event stream.
7. A typed `TerminationReason` maps to completed, failed, or cancelled run status and is committed
   atomically with the terminal event.
8. Evaluation reads immutable run/trace data; it does not mutate the original run.

## Data architecture

PostgreSQL is the production-like development system of record for agent definitions, runs, events,
memories, knowledge metadata, evaluations, and tool configuration. pgvector stores fixed-dimension
embeddings behind `VectorStore`; this path is verified against PostgreSQL 17 and the real vector
extension. Large source files may later move to object storage, referenced by metadata in
PostgreSQL.

SQLite remains the documented zero-infrastructure local/demo adapter and default when no
`DATABASE_URL` is supplied outside Docker. PostgreSQL is selected only by an explicit
`postgresql+asyncpg://...` URL and never silently falls back to SQLite. Both adapters preserve the
same repository/store boundaries. The default container runtime selects PostgreSQL exclusively and
fails closed; SQLite remains only the non-Docker local fallback.

## Container runtime topology

The production-like Compose stack has two networks. `web` and `api` share the normal app network;
`api` and `db` share an internal DB network. PostgreSQL is not published to the host, and Web never
receives DB or provider credentials. Host bindings are loopback-only for Web and API. Browser
requests and SSE stay same-origin through Next.js `/api` rewrites to Docker-internal `api:8000`.

FastAPI lifespan remains the sole current-schema and pgvector initialization boundary. The stack
runs one API process because ingestion and Evaluation workers are application-local; multiprocess
or horizontal scaling is not validated. PostgreSQL state, uploaded RAG sources, and generated DB
credentials live in separate named volumes. See `docs/CONTAINER_RUNTIME.md`.

## Frontend architecture

Use Next.js App Router with server components by default and client components only for interaction that requires browser state. Fetch server-owned data through typed API clients. Prefer Tailwind CSS plus native accessible elements and selective shadcn/ui primitives; avoid a large prebuilt component suite.

Initial product surfaces should eventually be agent definitions, runs, trace timelines, tool-call detail, knowledge sources, and evaluation results. Static examples must be clearly labeled fixtures and must never masquerade as live telemetry.

## Test seams

- `MockProvider` makes the primary runtime path deterministic without an API key.
- In-memory repository/store adapters support unit tests.
- PostgreSQL/pgvector integration tests verify SQL and vector behavior against the Compose service.
- Contract tests verify normalization between Agents SDK events and application events.
- Browser E2E tests exercise the real web-to-API-to-runtime path using deterministic providers.

## Delivery and quality pipeline

GitHub Actions treats Backend, PostgreSQL/pgvector, Frontend, Playwright, production image build,
Reliability, and synthetic Performance as independent bounded quality projections over the same
application contracts. Main delivery validation runs production Compose images from disposable
volumes and emits SHA/image/test evidence. It does not publish an image or deploy a service. Run and
RunEvent persistence remain product truth; CI summaries and performance artifacts are downstream
evidence and never a second runtime data store. See `docs/CI_RELIABILITY_PERFORMANCE.md`.

## Deferred decisions

Authentication/tenancy, durable background job infrastructure, artifact/object storage, formal
schema migrations, managed deployment, and internet-service readiness remain deferred until
measured requirements justify them. The application-
owned deterministic evaluation schema and local bounded worker are documented in
`docs/EVALUATION_DESIGN.md`.
