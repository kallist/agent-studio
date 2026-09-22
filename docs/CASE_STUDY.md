# Agent Studio — Engineering Case Study

Why this system is designed the way it is. Each claim below is grounded in source, tests, or commits in
this repository; `docs/V1_STATUS.md` is the claim boundary and `NOT TESTED` is used wherever evidence is
missing.

## Problem

Building an agent that answers a question is not the hard part. The hard parts are:

1. **Agent behavior is unobservable.** A chat transcript shows what the user saw, not which tool ran,
   what was retrieved, why a step stopped, or how many tokens it cost. When the answer is wrong there is
   nothing to inspect.
2. **Execution policy leaks into the model provider.** Step limits, retries, timeouts, tool permissions,
   and terminal states end up owned by whichever SDK is in use. Swapping providers then silently changes
   product behavior, and a provider's hosted sessions become the place truth lives.
3. **Retrieval is unauditable and can be wrong in a way nobody notices.** If re-ingesting a document
   fails halfway, stale and partial chunks can both be retrievable. Citations come from generated prose
   rather than from the retrieved record.
4. **Concurrency turns memory into a race.** "Remember this" and "stop remembering" arriving at the same
   time produce duplicate or policy-inconsistent facts unless ordering is enforced by the database.
5. **Evaluation is usually a separate script.** It re-implements the execution path, drifts from the
   product, and its traffic pollutes the usage metrics it is supposed to validate.

## Product goal

Make one Agent Run **observable, testable, explainable, and reproducible** end to end, without turning
the repository into a framework or a set of premature microservices. Concretely:

- A developer configures an Agent, attaches tools and knowledge, runs it, and inspects ordered evidence.
- The same execution path is used by the demo, by the tests, and by Evaluation.
- The default experience needs no API key, so anyone can reproduce it.
- Every quality claim names its evidence and its limitation.

## Architecture

Two deployable boundaries — a Next.js Studio and a FastAPI application — over PostgreSQL with pgvector.
The backend stays a modular monolith: `api/`, `application/`, `domain/`, `runtime/`, `tools/`,
`memory/`, `knowledge/`, `evaluation/`, `observability/`, `persistence/`.

The important boundary is not HTTP. It is this: **the model provider is a port, and the product owns
everything that decides what an Agent does.** `AgentRuntime` and `LLMProvider` are interfaces;
`AgentLoop`, `ToolExecutor`, Memory policy, retrieval visibility, persistence, redaction, and
Evaluation are application code. SDK objects and raw provider streams stop at the adapter.

See `docs/ARCHITECTURE.md` for contracts and `docs/RUN_LIFECYCLE.md` for the step-by-step execution
sequence.

## Key decisions

**Use the Agents SDK, but only behind an adapter.** The SDK is valuable as a provider/model integration
seam. It is not allowed to be the policy engine or the product database. Alternatively, hand-rolling
every provider HTTP client would have meant re-implementing streaming, tool-call parsing, and usage
normalization three times — so the adapter keeps the integration cheap while the boundary keeps the
behavior owned. SDK function callbacks are **capture-only**: a model-selected call becomes an
application `ToolCall` that only `ToolExecutor` may validate and execute.

**Keep the runtime boundary even though the repository is private.** `MockProvider` is not a testing
convenience bolted on at the end; it is the default runtime. It is what makes the demo, the offline
suite, the browser suite, and the container validation run without a key or a bill. It also forces the
runtime contract to be explicit, because two implementations must satisfy the same port.

**Store fixed-dimension embeddings in the database already in use.** pgvector gives vector search inside
the transactional store that already holds documents, chunks, runs, and events. A dedicated vector
database would have added a second consistency domain to a project whose central claim is that lineage
is trustworthy. The cost is a fixed `vector(256)` dimension and an index choice, and the benefit is that
"which generation is this chunk from" is a normal SQL join.

**Make completed-only visibility a property of every retrieval path.** Chunks are staged under a
generation and activated in one transaction; each of the four retrieval boundaries independently
requires a `completed` owning job. Repeating the predicate instead of centralizing it is deliberate:
a single missed filter would leak staged data, and the duplication is asserted by
`test_failed_dirty_generation_is_invisible_to_every_retrieval_boundary`.

**Serialize Memory policy on a database row.** Disable and Run finalization take a lock on the
Agent-owned memory row (`SELECT ... FOR UPDATE` on PostgreSQL, `BEGIN IMMEDIATE` on SQLite), and an
unknown dialect fails closed rather than degrading silently. An in-process lock would have been simpler
and would have proven nothing.

**Let Evaluation execute real Runs.** A grader that judges a re-implementation judges the wrong system.
Evaluation creates its own Agent snapshot and runs the real product path with `run_kind=evaluation`, then
projects only `run_kind=normal` Runs into dashboard metrics so regression traffic cannot inflate or
deflate usage numbers.

## Hard problems

Each problem was found in this repository's history and fixed; the sections name the fix commit, the
regression test, and the trade-off.

### 1. Failed re-ingestion leaked dirty data into retrieval

- **Problem.** Retrieval keyed on knowledge-base and document identity only. A replacement ingestion that
  failed after writing some vectors left those vectors retrievable alongside the previous generation, and
  cleanup that was interrupted left orphaned vectors that nothing referenced.
- **Why the naive design failed.** "Write chunks, mark the job complete" has no boundary between the old
  and the new generation. Between the first vector write and the completion flag, the document is in a
  state that is neither the old version nor the new one. Filtering on job state at *one* query would not
  have been enough either, because four different code paths retrieve chunks.
- **Solution** (`515d27f`, `224bd9c`). Chunks are written against their owning `ingestion_job_id` with a
  disjoint negative index range, so staged rows cannot collide with an activated generation. Activation
  deletes the previous generation and its vectors, normalizes the index to `0..N`, and marks the job
  completed — all in one transaction. Failure discards only that job's staged data. Every semantic,
  lexical, and citation-hydration boundary independently joins candidates to a `completed` job, so even
  orphaned rows left by an interrupted cleanup stay invisible. A startup migration for pre-existing
  chunks backfills a generation only when the document is unambiguous and leaves the column `NULL`
  otherwise, which fails closed because `NULL` is excluded by the join.
- **Regression tests.** `test_failed_vector_write_never_exposes_chunks_or_citations`,
  `test_failed_reingestion_preserves_last_completed_generation`,
  `test_failed_dirty_generation_is_invisible_to_every_retrieval_boundary`,
  `test_activation_failure_is_terminal_and_preserves_previous_generation`,
  `test_legacy_chunk_visibility_migration_is_fail_closed`,
  `test_pgvector_search_query_requires_completed_generation`.
- **Trade-off.** The same predicate is duplicated in four places, and staging wastes index space before
  normalization. In exchange, no single code path can reintroduce the leak, and the database state is
  never half-switched.

### 2. Memory writes raced with Memory being disabled

- **Problem.** Two concurrent Runs, or a Run finishing while a user disables Memory, could produce
  duplicate facts or a fact written after the user asked the Agent to stop remembering.
- **Why the naive design failed.** The first attempt (`32d0a92`) did read-and-write inside one
  transaction, which is necessary but not sufficient: two transactions can still interleave between the
  read and the write unless something serializes them, so both orderings were possible and neither was
  predictable.
- **Solution** (`cdb3773`). Changes to the memory-enabled setting and Run finalization both acquire a lock
  on the same Agent-owned row through `_serialized_agent_memory_transaction`, using
  `BEGIN IMMEDIATE` on SQLite and `SELECT ... FOR UPDATE` on PostgreSQL. Finalization reads the policy
  flag *inside* the lock and only then decides whether to write. The result is deterministic: whichever
  transaction acquires the lock first wins, producing disable-wins and finalization-wins outcomes that
  tests can assert. Unsupported dialects raise instead of pretending to serialize.
- **Regression tests.** `test_disable_wins_serialization_before_run_finalization`,
  `test_finalization_wins_then_disable_blocks_future_writes`,
  `test_postgresql_memory_row_locks_prove_both_orderings`, `test_terminal_event_failure_rolls_back_memory_and_run_completion`.
- **Trade-off.** Every Memory finalization now takes a write lock on one row, which limits throughput on a
  hot Agent. At v1 scale — one local user — determinism is worth far more than parallelism, and the
  serialization point is explicit rather than emergent.

### 3. Provider compatibility is not provider identity

- **Problem.** DeepSeek exposes an OpenAI-compatible Chat Completions API. Treating the compatible client
  as "an OpenAI provider" would have mislabeled provider identity in every persisted event, and would have
  sent Responses-only settings (`previous_response_id`, `store`, hosted tools) to an endpoint that does
  not implement them.
- **Why the naive design failed.** Syntax compatibility is a much weaker property than capability
  compatibility. The tempting shortcut — reuse the OpenAI path with a different base URL — quietly breaks
  on the fields where the two APIs disagree, and produces traces that cannot answer "which provider
  actually ran this".
- **Solution** (`f568029`). An explicit provider resolver selects an API style per provider. DeepSeek gets
  its own key, validated official base URL, bounded transport policy, and Chat Completions model, and its
  thinking mode is explicitly disabled rather than mapped mechanically from OpenAI reasoning settings.
  Events persist `provider=deepseek` with the API style, model, and aggregate usage; raw SDK objects,
  chunks, and credentials never cross the adapter. There is no silent fallback in either direction.
- **Regression tests.** The offline contract suite for the adapter, plus opt-in live tests:
  `test_real_deepseek_basic_chat_stream_usage_and_identity`,
  `test_real_deepseek_calculator_is_model_selected_then_application_executed`,
  `test_real_deepseek_rag_uses_completed_ingestion_and_citations`,
  `test_real_deepseek_memory_write_and_retrieval_use_product_path`,
  `test_real_deepseek_evaluation_uses_linked_evaluation_run`. Live tests require
  `RUN_REAL_DEEPSEEK_TESTS=1` and a key, and run from a manual protected workflow, not a pull request.
- **Trade-off.** Provider-specific adapters cost more code than one shared client, and the OpenAI path is
  implemented but its live execution remains **NOT TESTED** because no live validation was performed for
  it. That asymmetry is reported rather than smoothed over.

### 4. A reachable backend is not a healthy backend

- **Problem.** A structured `5xx` from the backend could still leave the UI looking connected, because
  reachability was treated as health.
- **Why the naive design failed.** TCP and HTTP transport success says nothing about whether the
  application can serve a request. Inferring health from "the fetch resolved" makes the connection
  indicator a decorative light.
- **Solution** (`e472d84`). Health is derived from the request contract: a non-2xx response reports API
  failure, and recovery is only shown after a real success. The combined browser flow that exposed this
  became a regression scenario.
- **Regression test.** The combined-flow scenario in `apps/web/e2e/vertical-slice.spec.ts` and the
  readiness assertions behind it.
- **Trade-off.** The UI needs explicit failure and recovery states instead of a single boolean, which adds
  state to the client but makes the indicator mean something.

### 5. Delivery evidence is not deployment

- **Problem.** Successful container tests are easy to describe as "deployed", which would have been false:
  nothing is published and nothing is hosted.
- **Why the naive design failed.** "CD" is ambiguous. Under time pressure, built-and-validated slides into
  shipped.
- **Solution** (`acf5edf`, `a65c429`). `DELIVERY READY` is defined narrowly as: this commit's production
  images built and its disposable Compose runtime passed the documented smoke and E2E checks. The workflow
  pushes no registry image and deploys no target. Failure to clean up removes the readiness artifact rather
  than reporting success.
- **Regression evidence.** The Delivery workflow and `scripts/ci/docker_reliability.py`, which operates
  only within a validated project-scoped Compose project.
- **Trade-off.** A stricter definition means the pipeline proves less than a deployment pipeline would, and
  says so.

## Testing

The test strategy exists to make claims falsifiable, and it is organized by what each layer can prove.

| Layer | Tool | What it proves |
|---|---|---|
| Unit and application | pytest, offline by default | Loop bounds, tool boundaries, Memory policy, RAG visibility, redaction, API contracts |
| Real database | pytest against PostgreSQL 17 + pgvector 0.8.6 | Real vector extension, `vector(256)`, HNSW, row-lock interleavings, completed-only SQL |
| Frontend | Vitest + React Testing Library | Component behavior, i18n dictionary parity |
| Browser | Playwright, Mock-only | The real web → API → runtime path, including RAG citations and Evaluation |
| Reliability | pytest markers + container runner | Concurrency, cancellation, timeouts, restart recovery, persistence across restarts |
| Performance | pytest against PostgreSQL | Synthetic p50/p95/throughput regression baseline |
| Delivery | Compose runner | Fresh images start, persist, recover, and pass container-targeted E2E |

The default offline selection runs **206 tests** with provider, PostgreSQL, and performance cases
deselected, so a normal pull request needs no key, no database, and no bill. Live provider tests are opt-in
and run from a manual protected-environment workflow.

Two deliberate testing choices are worth calling out. First, mock usage is reported as `N/A` rather than
`0`, because zero tokens would falsely imply a metered call that consumed none. Second, the performance
numbers are engineering regression thresholds, not achievements: they were measured on one Windows machine
against Mock, and the thresholds are intentionally wide (`1.5x` report-only, `4x` or quarter-throughput
blocking) because GitHub-hosted runners are noisy.

## Reliability

- Bounded execution: step limit, total timeout, cancellation checked between and during provider calls,
  bounded retries for invalid structured output only, context and decision size ceilings, and per-tool call
  limits that also catch changed-argument repeats.
- Persistence ordering: the terminal event and the terminal Run status commit in one transaction, so a Run
  cannot be left non-terminal by a partial finalization.
- Restart semantics: normal Runs are not resumable and are failed explicitly with a `process_restart`
  category; ingestion requeues abandoned jobs; Evaluation marks an interrupted case `ERROR` and resumes the
  Evaluation run.
- Failure recovery is verified against a real stack, including database down/up transitions, connection
  pool recovery after restart, and browser reload of persisted evidence.

## Limitations

Agent Studio v1 is a single-user local workbench and must not be exposed as a public or shared service.

- No authentication, authorization, RBAC, multi-tenancy, or global rate limiting.
- No horizontal or multiprocess API operation; the Docker stack runs one API process because ingestion and
  Evaluation workers are application-local. Managed PostgreSQL is **NOT TESTED**.
- No distributed workers, Kubernetes, public TLS/ingress, backup automation, or cloud secret management.
- Real OpenAI Responses, OpenAI embeddings, OpenAI with pgvector, and internet production load are
  **NOT TESTED**.
- No chaos engineering, high availability, zero-downtime delivery, or production SLA, and none is claimed.
- Ingestion supports plain text, Markdown, and text-extractable PDF; retrieval quality is not benchmarked
  against published datasets.

The full list, with status per capability, is `docs/V1_STATUS.md`.

## Lessons learned

- **A boundary you cannot test is not a boundary.** The runtime port only became real once a second
  implementation had to satisfy it. Mock-first was a design decision, not a testing afterthought.
- **Async job status must participate in data visibility.** "Complete" is not a display flag; it is part of
  the retrieval query.
- **Policy guarantees need database ordering evidence.** Locking, transaction boundaries, and both
  interleavings must be asserted, or the guarantee is a comment.
- **Duplicating a safety predicate can be the safer choice.** When one missed check leaks data, repeating
  the check per path and asserting it is better than a single elegant chokepoint.
- **Naming operational claims precisely is engineering work.** "Delivery ready", "NOT TESTED", and
  "regression baseline" prevent a project from slowly claiming more than it can show.

## Where to read the code

| Concern | Entry point |
|---|---|
| Bounded execution | `apps/api/app/runtime/engine.py` |
| Limits and typed contracts | `apps/api/app/domain/contracts.py` |
| Provider adapters and Mock | `apps/api/app/runtime/providers.py`, `apps/api/app/runtime/agents_sdk.py`, `apps/api/app/runtime/mock.py` |
| Tool validation and execution | `apps/api/app/tools/registry.py`, `apps/api/app/tools/calculator.py` |
| Retrieval and citations | `apps/api/app/knowledge/service.py`, `apps/api/app/knowledge/vector_store.py` |
| Ingestion generation consistency | `apps/api/app/knowledge/repository.py` |
| Memory policy and transactions | `apps/api/app/memory/policy.py`, `apps/api/app/persistence/repositories.py` |
| Evaluation | `apps/api/app/evaluation/service.py`, `apps/api/app/evaluation/graders.py` |
| Observability and redaction | `apps/api/app/observability/aggregation.py`, `apps/api/app/observability/redaction.py` |
| Container runtime | `compose.yaml`, `apps/api/Dockerfile`, `apps/web/Dockerfile`, `scripts/docker-up.ps1` |
| CI and delivery gates | `.github/workflows/ci.yml`, `.github/workflows/delivery.yml`, `scripts/ci/` |
