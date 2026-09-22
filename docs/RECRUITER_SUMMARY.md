# Agent Studio — Recruiter Summary

One page. What it is, what problem it solves, what is technically interesting, and how to verify it.

---

## Project

**Agent Studio** — a full-stack workbench for building, running, and debugging tool-using AI agents.

A local, single-user platform where an Agent's whole lifecycle is explicit: define it, attach tools and a
knowledge base, give it durable memory, run it, inspect the ordered trace, and score the result with
deterministic graders. Every step, tool call, retrieval, and Memory write is persisted as ordered evidence
rather than inferred from a chat transcript.

Not a chatbot UI, not a framework, not a managed service.

## Role

Sole designer and developer: architecture, backend, frontend, data model, retrieval, infrastructure, CI,
and the test strategy. Agent Studio is a personal project, not a client or employer engagement.

## Problem

Agent systems are easy to demo and hard to operate. A transcript does not show which tool ran, what was
retrieved, or why the loop stopped. Execution policy drifts into whichever SDK is used, so behavior changes
when the provider changes. Failed document re-ingestion can leave partial data retrievable, and concurrent
Memory writes can duplicate or contradict a user's instructions. Evaluation usually re-implements the
execution path, so it grades something other than the product.

## Solution

- **The application owns execution.** The model provider is a port; `AgentLoop` owns step limits, total
  timeout, cancellation, bounded retry, duplicate-call suppression, event ordering, and typed termination.
- **Nothing incomplete is retrievable.** Chunks stage under an ingestion generation and activate in one
  transaction; all four retrieval paths independently require a completed generation.
- **Ordering is enforced by the database.** Memory policy changes and Run finalization serialize on one
  Agent-owned row, yielding deterministic disable-wins and finalization-wins outcomes.
- **One lineage, three views.** Persisted `Run` plus ordered `RunEvent` backs the live trace, the
  dashboard, and Evaluation — and Evaluation executes real isolated Runs on its own Agent snapshot.
- **Runs without a key.** The default runtime is a deterministic Mock provider, so the whole product is
  reproducible from a clean clone with no credentials.

![Dashboard with persisted runs and measured telemetry](assets/dashboard.png)

## Technical highlights

| Area | What is notable |
|---|---|
| Agent runtime | Application-owned bounded loop behind provider ports; SDK callbacks are capture-only, so the model can never execute a tool directly |
| Tool safety | Registry only registers; `ToolExecutor` alone validates schema, permissions, timeout, output limits, and per-tool call limits |
| RAG consistency | Generation staging with a disjoint index range, atomic activation, and completed-only enforcement duplicated across four independently tested retrieval boundaries |
| Memory concurrency | Row-lock serialization on PostgreSQL (`SELECT ... FOR UPDATE`) and SQLite (`BEGIN IMMEDIATE`), failing closed on unknown dialects |
| Data | PostgreSQL 17 with pgvector `vector(256)` and HNSW, plus a documented SQLite host-development fallback and no silent fallback in either direction |
| Observability | Events are redacted and persisted before publication, so stored and streamed payloads are identical |
| Delivery | Production-like Compose stack with non-root read-only containers, internal-only database, loopback bindings, and runtime secret volumes |
| Quality gates | Seven independent CI jobs plus a Delivery Validation workflow that builds fresh images and exercises the whole stack |

## Evidence

Every capability claim carries a status and a source. Nothing here is estimated.

| Claim | Evidence |
|---|---|
| Backend correctness | **206 offline tests pass**, 26 provider/database/performance cases deselected; Ruff and strict `mypy` clean |
| Real database behavior | Suites run against real PostgreSQL 17 + pgvector 0.8.6, asserting the vector extension, `vector(256)`, HNSW, row-lock interleavings, and completed-only SQL |
| Browser behavior | 18 deterministic Mock-only Playwright scenarios over the real web → API → runtime path |
| Reliability | Cancellation, timeout, concurrency, event ordering, queue bounds, and restart recovery, plus container restart and persistence validation |
| Docker quick start | Executed on a clean checkout: fresh Compose stack healthy, `/health` 200, same-origin `/api` proxy working, and a Mock Agent run completing `Calculate 128 * 37 + 456` → `5192` with no provider key configured |
| Provider status | DeepSeek: real online validation. OpenAI Responses and embeddings: implemented, **live NOT TESTED** |
| Performance | Synthetic p50/p95 regression baseline over nine scenarios — reported as a regression guard, not as a speed claim |
| Capability matrix | [docs/V1_STATUS.md](V1_STATUS.md) lists implemented, tested, and not-tested status per capability with its primary source |

## Limitations

Stated plainly, because they are part of the engineering position: no authentication, authorization, RBAC,
or multi-tenancy; no horizontal or multiprocess operation; managed PostgreSQL not tested; no distributed
workers, Kubernetes, public TLS/ingress, backup automation, or cloud secret management; real OpenAI and
internet production load not tested; no production SLA claimed. V1 is a single-user local workbench and
must not be exposed as a public or shared service.

## Links

- Source: <https://github.com/kallist/agent-studio>
- [README](../README.md) · [Engineering case study](CASE_STUDY.md) · [Architecture](ARCHITECTURE.md)
- [Run lifecycle](RUN_LIFECYCLE.md) · [RAG lifecycle](RAG_LIFECYCLE.md) · [Security design](SECURITY_DESIGN.md)
- [Portfolio case](PORTFOLIO.md) · [Interview guide](INTERVIEW_GUIDE.md)
