# Agent Studio architecture

## Goals

The first version should make a real agent run observable from definition through evaluation without turning the repository into a framework or a set of premature microservices. The web and API applications are separate deployable boundaries; backend modules remain a modular monolith until scaling or ownership evidence justifies extraction.

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

The frontend never calls an LLM provider or a tool directly. FastAPI owns authentication and API contracts. `AgentService` coordinates application workflows. `AgentRuntime` executes a run behind a stable port. Persistence and retrieval are accessed through repositories/stores rather than ORM sessions in business code.

## Recommended repository structure

```text
agent-studio/
├── apps/
│   ├── web/                 # Next.js application
│   └── api/                 # FastAPI modular monolith
├── docs/
│   └── ADR/                 # Architecture decisions
├── infra/                   # Local/deployment infrastructure
├── tests/                   # Cross-application integration and E2E tests
├── compose.yaml             # Local PostgreSQL/pgvector
├── AGENTS.md
└── README.md
```

This keeps worktree changes easy to isolate by application without introducing a monorepo framework or shared-package build system before one is needed.

## Backend boundaries

The eventual `apps/api` package should be organized by responsibility, not by transport:

```text
app/
├── api/             # HTTP routes and dependency wiring
├── application/     # AgentService and use cases
├── domain/          # Entities, value objects, policies, ports
├── runtime/         # AgentRuntime implementations and SDK adapter
├── tools/           # Tool registry, validation, execution adapters
├── memory/          # Memory policies and store adapters
├── knowledge/       # Ingestion, retrieval, VectorStore adapters
├── tracing/         # Runtime event model and TraceStore adapters
└── persistence/     # SQLAlchemy models and repository adapters
```

These are module boundaries inside one FastAPI service, not separate services.

## Core contracts

### AgentService

Application-level coordinator. It validates requests, loads an agent definition, creates a run record, invokes `AgentRuntime`, persists events and terminal state, and returns a run view. It owns transaction and idempotency policy but not HTTP details or provider-specific calls.

### AgentRuntime

Port for executing or resuming an agent run. Its inputs and emitted events are application types. The initial production adapter is `AgentsSdkRuntime`; deterministic tests use a fake/runtime fixture. SDK result objects do not cross this boundary.

### LLMProvider

Port for model/provider selection, credentials, capabilities, and model invocation needed by a runtime adapter. `OpenAIProvider` creates the real OpenAI-backed implementation. `MockProvider` returns deterministic scripted outputs and tool requests without a network or API key.

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

PostgreSQL is the system of record for agent definitions, versions, runs, events, memories, knowledge metadata, evaluations, and tool configuration. pgvector stores embeddings behind `VectorStore`. Large source files may later move to object storage, referenced by metadata in PostgreSQL.

The first version uses Docker Compose for local PostgreSQL/pgvector. SQLite may be introduced only as a documented temporary adapter when PostgreSQL blocks a vertical slice; the repository ports remain unchanged.

## Frontend architecture

Use Next.js App Router with server components by default and client components only for interaction that requires browser state. Fetch server-owned data through typed API clients. Prefer Tailwind CSS plus native accessible elements and selective shadcn/ui primitives; avoid a large prebuilt component suite.

Initial product surfaces should eventually be agent definitions, runs, trace timelines, tool-call detail, knowledge sources, and evaluation results. Static examples must be clearly labeled fixtures and must never masquerade as live telemetry.

## Test seams

- `MockProvider` makes the primary runtime path deterministic without an API key.
- In-memory repository/store adapters support unit tests.
- PostgreSQL/pgvector integration tests verify SQL and vector behavior against the Compose service.
- Contract tests verify normalization between Agents SDK events and application events.
- Browser E2E tests exercise the real web-to-API-to-runtime path using deterministic providers.

## Deferred decisions

Authentication/tenancy, background job infrastructure, artifact/object storage, production deployment, and the exact evaluation schema are intentionally deferred until the first vertical slice provides evidence. They must not be guessed into the baseline.
