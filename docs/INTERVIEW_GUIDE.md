# Agent Studio interview guide

This guide exists so the project author can explain their own system accurately under pressure. Answers
are grounded in this repository: each one names the concept, the way Agent Studio actually implements it,
and the trade-off that was accepted. Where the honest answer is "that is not implemented", it says so.

## Top 10 questions, fastest answers

Read this table first. The detailed sections below expand each row.

| # | Question | One-line answer |
|---|---|---|
| 1 | What is Agent Studio? | A workbench that runs an Agent end to end and persists every decision as ordered evidence, so behavior can be explained and evaluated instead of guessed at from a transcript. |
| 2 | Why own the AgentLoop instead of letting the SDK drive? | Step limits, retries, timeout, cancellation, tool permissions, and terminal state are product policy; if the SDK owns them, swapping providers silently changes product behavior. |
| 3 | How do you know a tool call is safe? | SDK callbacks are capture-only; a selected call becomes an application `ToolCall` that only `ToolExecutor` validates and runs, so no Python callable from the model can bypass validation. |
| 4 | What is the hardest consistency bug you fixed? | Failed re-ingestion leaked partial and orphaned chunks into retrieval, because identity-keyed retrieval has no boundary between the old and new generation. |
| 5 | How do you guarantee retrieval only sees good data? | Chunks stage under a generation with a disjoint index range and activate in one transaction; all four retrieval boundaries independently require a `completed` job. |
| 6 | Why does Memory need a transaction at all? | Read-then-write is not enough — without a serialization point, disable and finalization interleave and produce duplicate or policy-violating facts. |
| 7 | Why `SELECT FOR UPDATE`? | It serializes settings changes and Run finalization on one Agent-owned row, making disable-wins and finalization-wins deterministic instead of racy. |
| 8 | What does the Mock actually prove? | That the application contract is real and reproducible: same loop, tools, RAG, Memory, events, and persistence path with zero network. It cannot prove real provider behavior. |
| 9 | Why does Evaluation execute real Runs? | A grader judging a re-implementation judges the wrong system; Evaluation runs the product path with its own Agent snapshot and `run_kind=evaluation`. |
| 10 | Why is Docker a single API process? | Ingestion and Evaluation workers are application-local, so multiprocess operation could double-claim work; distribution needs leasing and idempotency design that v1 does not have. |

## Opening pitches

Say the 30-second version when asked "tell me about this project"; use the two-minute version when they
ask a follow-up; use the five-minute walk-through when they say "go deeper on the architecture".

### 30-second pitch

Agent Studio is a development and debugging platform for AI Agents. Instead of hiding behavior behind a chat UI, it owns a bounded execution loop and persists tool calls, RAG citations, Memory events, and terminal state so each Run can be traced and deterministically evaluated. The default demo is offline Mock; DeepSeek is real-tested; PostgreSQL/pgvector and a production-like Docker stack make the engineering path concrete.

### Two-minute pitch

The browser talks to Next.js and FastAPI. `AgentService` creates a persisted Run, then an application-owned `AgentLoop` asks a provider for one typed decision per bounded step. A provider can return a final answer or a captured tool request; only `ToolExecutor` can validate and execute it. Knowledge retrieval and durable Memory are assembled as untrusted context. Every lifecycle transition is persisted as an ordered RunEvent before the UI projects it into live trace and dashboard views. Evaluation clones the Agent snapshot, executes real isolated Runs, and applies deterministic graders with PASS, FAIL, or ERROR. The recommended Docker path uses PostgreSQL 17/pgvector, non-root images, internal DB networking, generated runtime secrets, and CI gates. The deliberate v1 boundary excludes Auth, multi-tenancy, distributed workers, Kubernetes, and live OpenAI claims.

### Five-minute architecture walk-through

1. **Web boundary:** Next.js provides Agent Builder, Playground, Knowledge, Memory, Run Detail, Dashboard, and Evaluations; it never receives database/provider credentials.
2. **API workflow:** thin FastAPI routes call application services. The service persists pending state and invokes a stable `AgentRuntime` port.
3. **Execution:** `AgentLoop` owns bounds, cancellation, retries, context limits, duplicate-call policy, and typed termination. Mock and the Agents SDK adapter share this contract.
4. **Capabilities:** server-owned ToolRegistry/ToolExecutor controls tools; RAG exposes completed generations and citations; Memory applies Agent-scoped policy and transaction ordering.
5. **Lineage:** Run plus ordered RunEvent is the source of truth. Live SSE, Run Detail, Dashboard, and Evaluation are projections.
6. **Persistence and delivery:** SQLite is the local fallback; Docker uses PostgreSQL/pgvector. CI separately validates code, real DB behavior, browser flows, containers, reliability, performance, and fresh-stack delivery.

## Quick answers

The short form of each answer. The [deep-dive section](#deep-dive-answers) explains the reasoning, and
the [engineering stories](#engineering-stories-star) are the ones to tell out loud.

### 1. Why does the application own AgentLoop?

**Short:** Product limits, termination, tools, persistence, and audit semantics must not change with an SDK.

**Deep:** The provider adapter supplies typed decisions and normalized usage, while AgentLoop owns steps, retries, cancellation, context limits, duplicate-call policy, event ordering, and terminal mapping. This keeps deterministic Mock and real providers behaviorally comparable.

### 2. Why keep the Agents SDK?

**Short:** It provides a useful provider/model integration seam without becoming the product database or policy engine.

**Deep:** SDK types and raw streams stop at `AgentsSdkRuntime`; capture-only callbacks prevent SDK tool execution from bypassing application validation.

### 3. Why persist Run?

**Short:** Run is the durable identity and terminal outcome for reproducibility and links.

**Deep:** It snapshots Agent identity/version, input/output, timestamps, kind, failure, and termination so refresh, dashboard, evaluation lineage, and restart recovery do not depend on process memory.

### 4. Why are RunEvents more than logs?

**Short:** They are ordered, typed domain evidence with correlation fields.

**Deep:** Events carry sequence, step index, tool-call ID, duration, safe payload, and terminal meaning. Observability and graders consume them as contracts; logs remain operational text.

### 5. Why does upload return 202?

**Short:** Validation and job creation are synchronous; parsing/embedding is bounded background work.

**Deep:** The durable ingestion job exposes queued/processing/completed/failed state and enables restart recovery without holding an HTTP connection.

### 6. Why completed-only RAG?

**Short:** Users must never retrieve partial or failed replacement data.

**Deep:** Chunks are generation-scoped and activated only when the job completes. Search excludes queued, processing, failed, and superseded generations, including concurrent re-ingestion windows.

### 7. Why server-owned citations?

**Short:** Provider prose is not provenance.

**Deep:** Citation metadata comes from retrieved chunk/document records and is persisted with the tool result; the UI never invents source identity from model text.

### 8. Why separate semantic, lexical, and hybrid retrieval?

**Short:** Exact identifiers and semantic paraphrases fail differently.

**Deep:** Both adapters implement one port; hybrid combines ranked evidence deterministically while preserving metadata filters and testable scores.

### 9. Why is Memory Agent-scoped?

**Short:** A fact from one Agent must not silently affect another.

**Deep:** Every store/retrieval/delete operation includes Agent identity. Evaluation additionally uses evaluation-owned Agent clones so test fixtures do not pollute the source Agent.

### 10. Why `SELECT FOR UPDATE`?

**Short:** PostgreSQL must serialize conflicting Memory finalization/setting changes.

**Deep:** Locking the Agent row creates deterministic disable-wins/finalization-wins order and prevents concurrent duplicate writes; SQLite uses an adapter-appropriate serialized transaction.

### 11. Why not save every message?

**Short:** Durable Memory needs explicit policy, not an unbounded transcript copy.

**Deep:** Policy bounds content, detects save-worthy facts, ranks retrieval by relevance/recency/importance, deduplicates, expires, and supports user-visible deletion/disable.

### 12. Why does Evaluation use real Runs?

**Short:** A grader should judge the same execution path used by the product.

**Deep:** Each Case executes an isolated Agent snapshot with `run_kind=evaluation`; graders reference the persisted Run/events without duplicating traces.

### 13. What is PASS vs FAIL vs ERROR?

**Short:** PASS meets expectations, FAIL is a behavior mismatch, ERROR means execution or grading could not produce a valid judgment.

**Deep:** Keeping them separate prevents infrastructure failures from looking like low model quality and preserves useful per-grader evidence.

### 14. Why exclude Evaluation from Dashboard?

**Short:** Regression traffic would distort normal usage and success metrics.

**Deep:** `run_kind` preserves lineage while dashboard queries intentionally project only normal Runs.

### 15. Why is DeepSeek not called an OpenAI provider?

**Short:** Compatible client syntax does not erase provider identity or API semantics.

**Deep:** Events persist `provider=deepseek` and Chat Completions style. Credentials, base URL validation, capability differences, defaults, and tracing policy remain separate.

### 16. Why are performance thresholds wide?

**Short:** GitHub-hosted runners are noisy; the gate targets catastrophic regressions, not fake precision.

**Deep:** A reviewed baseline records p50/p95/throughput; 1.5x is report-only and 4x/quarter-throughput is blocking. Functional failures always block and baseline changes require review.

### 17. Why no Auth, Redis, or Kubernetes in v1?

**Short:** They do not improve the core proof that Agent behavior is observable and reproducible.

**Deep:** Adding shared-service exposure before Auth/tenancy, or distributed infrastructure before worker semantics, would widen risk and dilute correctness. The single-user local boundary is explicit.

## Deep-dive answers

The questions an interviewer asks second. Each answer is the concept, then what Agent Studio does, then
the trade-off.

### Why not let the provider SDK own the loop?

Because the loop is where product policy lives. The Agents SDK is genuinely useful for streaming,
tool-call parsing, and usage normalization, so the project keeps it — behind `AgentRuntime`. What it does
not get to own is step limits, total timeout, cancellation, retry policy, duplicate-call suppression,
event ordering, or the mapping from a termination reason to a Run status. Those live in
`apps/api/app/runtime/engine.py`. The trade-off is more adapter code and a contract test suite to keep
Mock and real providers behaviorally comparable, in exchange for a product whose behavior does not change
when a provider is swapped.

### Why does Mock exist, and what can it not prove?

`MockProvider` is the default runtime, not a test stub bolted on the side. It is why the demo, the offline
pytest selection, the Playwright suite, and the container validation all run with no key and no bill, and
it is why the runtime port had to be explicit — a second implementation must satisfy the same contract.
It cannot prove provider-specific behavior: real streaming chunk shapes, real tool-call encoding, real
usage accounting, real rate limits, or real latency. That is exactly why DeepSeek has an opt-in live suite
and why OpenAI is reported as **NOT TESTED** rather than inferred to work from a shared client library.

### Why is Mock usage shown as N/A instead of 0?

Because zero tokens would be a false measurement. `0` implies a metered model call that consumed nothing;
`N/A` says no model request occurred. The usage field is nullable so "not measured" and "measured zero"
stay distinguishable, which matters when reading a trace to work out whether a cost came from the model
or from the tool path.

### Why pgvector rather than a dedicated vector database?

Three reasons. The project's central claim is that lineage is trustworthy, and lineage spans documents,
chunks, ingestion jobs, runs, and events — putting vectors in a second store would create a second
consistency domain that no transaction spans. "Which generation owns this chunk" is then a normal SQL
join rather than an application-level reconciliation. And the operational cost stays at one database in
Compose. The trade-off is a fixed `vector(256)` dimension, an HNSW index choice, and no specialized vector
features; the `VectorStore` port keeps that decision reversible, and no pgvector operator appears in
domain or application code.

### Why semantic, lexical, and hybrid instead of one mode?

They fail differently. Semantic search handles paraphrase and misses exact identifiers; lexical search
handles exact tokens such as an error code or a codename and misses paraphrase. Hybrid combines ranked
evidence deterministically behind one port, preserving metadata filters and testable scores. The trade-off
is a second ranking path to test, which is why all retrieval modes share the same completed-only gate and
the same citation hydration.

### How does a failed ingestion avoid polluting retrieval?

Generation staging plus atomic activation. Chunks are written against their owning `ingestion_job_id`
with a negative index range that cannot collide with an activated generation. Activation deletes the
previous generation and its vectors, normalizes the index to `0..N`, and marks the job `completed` in a
single transaction. Failure discards only that job's staged data, so the last good generation stays
retrievable. Then, because cleanup can itself be interrupted, all four retrieval boundaries independently
join candidates to a `completed` job — so even orphaned rows left behind stay invisible.

### Why duplicate the completed-only check in four places?

Because a single chokepoint that one code path forgets to call leaks data, while four explicit predicates
are each individually testable. `test_failed_dirty_generation_is_invisible_to_every_retrieval_boundary`
constructs orphaned vectors by hand and then asserts that lexical search, semantic search, hybrid search,
and citation hydration each return nothing. The trade-off is real duplication; the alternative was a
shared helper that is easy to bypass and hard to prove complete.

### Why does Memory need both a transaction and a lock?

The transaction makes the write atomic; the lock makes the interleaving deterministic. The first
implementation did read-policy-then-write inside one transaction, which is necessary but not sufficient,
because two transactions can still interleave between the read and the write. `cdb3773` moved both the
settings change and Run finalization through `_serialized_agent_memory_transaction`, which takes a lock on
the Agent-owned row —`BEGIN IMMEDIATE` on SQLite, `SELECT ... FOR UPDATE` on PostgreSQL — and raises on
any other dialect instead of pretending to serialize. Finalization reads the policy flag inside the lock
and only then decides whether to write, which yields the two deterministic outcomes the tests assert.

### Why is `SELECT FOR UPDATE` not overkill for a single-user local app?

Because the race does not require multiple users. Two concurrent Runs for one Agent, or a Run finishing
while the user disables Memory, are both reachable from a single browser session. An in-process lock would
have been simpler and would have proven nothing about the persistence boundary, and the project's claim is
about database-enforced ordering, not about luck.

### What do the tests actually cover, and what is not tested?

They cover the offline application path, real PostgreSQL and pgvector behavior, the real web-to-API-to-runtime
path in a browser, reliability scenarios including cancellation, timeout, concurrency, and restart recovery,
a synthetic performance baseline, and a fresh-container delivery smoke. They do not cover live OpenAI,
internet-scale load, multi-process operation, managed PostgreSQL, or multi-user security, all of which are
recorded as `NOT TESTED` or `NOT IMPLEMENTED`. The Mock-based tests also cannot validate real provider
semantics, which is why the DeepSeek suite exists as a separate opt-in tier.

### Why not call the DeepSeek path "OpenAI-compatible and therefore OpenAI-tested"?

Because a compatible client syntax is a much weaker property than compatible behavior. DeepSeek runs Chat
Completions; OpenAI's implemented path here is Responses. Persisting `provider=openai` for a DeepSeek run
would corrupt exactly the lineage this project exists to provide, and sending Responses-only fields
(`previous_response_id`, `store`, hosted tools, `truncation`) to a Chat Completions endpoint would fail in
ways that look like model errors. So provider identity, API style, base URL validation, credentials, and
capability defaults are all separate, and each provider keeps its own readiness reporting.

### How are API keys handled?

Server side only, and never persisted. `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` come from the server
environment or a runtime secret file, and configuring both at once fails closed. The Docker helper streams
the value over stdin into a project-scoped volume mounted only into the API container, so the key is not a
build argument, a source file, a command-line value, or a persistent container environment value. Events
store provider identity and usage, never credentials, and `apps/api/app/observability/redaction.py` strips
labelled secrets from payloads before persistence — so the stored payload and the live stream carry
identical safe data. Compose validation also asserts that no service is privileged or mounts the Docker
socket, and that PostgreSQL has no host port.

### Why is there no authentication?

Because adding Auth properly means sessions, credential storage, password reset, authorization per
resource, and tenancy — and half of that is worse than none, since it invites exposure while remaining
unsafe. v1 instead binds Web and API to loopback, keeps PostgreSQL on an internal network, and states
plainly that it must not be exposed as a public or shared service. The frontend also never receives
database or provider credentials, so the API remains the place where an authentication boundary would go.

### Why does normal CI never call DeepSeek?

Default gates must be deterministic, secret-free, and non-billable. `ci.yml` sets both provider keys to
empty strings and both live flags to `0`, so an ordinary pull request runs fully offline. Real DeepSeek
validation lives in `provider-live.yml`, which is manual-only, bound to a protected environment, and
explicitly not a merge gate. The trade-off is that merge confidence does not include live provider
behavior; that is reported separately rather than blurred into one status.

### Why only one API process in Docker?

Because ingestion and Evaluation workers are application-local and claim persisted work. Two API processes
could double-claim the same ingestion job or Evaluation case without a leasing and idempotency design that
v1 does not have. Running one process is the honest configuration; horizontal operation is documented as
`NOT TESTED` rather than implied by the presence of a container.

### What would v2 change, and in what order?

The order is driven by what blocks a real deployment, not by what is fashionable. First authentication and
authorization, because that is the hard gate on any shared exposure. Then a multi-process or distributed
worker design with explicit leasing and idempotency, since that is what currently forces a single API
process. Then formal schema migrations before the schema has to evolve in place, and object storage for
large source files. Evaluation would grow LLM-as-a-judge graders only after the deterministic graders and
their isolation guarantees are proven, and managed PostgreSQL plus TLS/ingress only once there is a
deployment target to secure.

## Trade-off stories

The questions where the honest answer is "yes, that would work, and here is why I did not do it". Each
one names the alternative that was rejected, the cost that was accepted, and the point at which the
decision should be revisited.

### Why no Redis or Celery?

Both would give real queue infrastructure and a natural place to push work out of the API process. The
rejected alternative was a Redis-backed broker with a Celery worker for ingestion and Evaluation.
Ingestion and Evaluation are already durability-backed — the job row is persisted first, the worker
claims it, and startup recovery requeues abandoned work — so a broker would add a second system of record
for state that already has one, plus a new failure mode where the broker is up but the claim state is
inconsistent. The accepted cost is that workers live in the API process, which is exactly why the Docker
stack runs one API process and why horizontal operation is `NOT TESTED`. Revisit when ingestion volume or
Evaluation duration actually exceeds one process, and bring leasing plus idempotency with it rather than
just a broker.

### Why not a dedicated vector database?

A specialized store would offer better index tuning, richer filtering, and no fixed embedding dimension.
The rejected alternative was moving vectors into a separate service and keeping relational data where it
is. The product's central claim is that lineage is trustworthy, and lineage runs from document to chunk to
ingestion job to retrieved citation to Run event; splitting vectors out would create a second consistency
domain that no transaction spans, which is precisely the class of bug the generation work had to fix.
Against that, pgvector keeps everything in the database that already holds documents, jobs, runs, and
events, so "which generation owns this chunk" is an ordinary SQL join. The accepted costs are a fixed
`vector(256)` dimension, an HNSW index choice, and no vector-specific features. `VectorStore` is a port and
no pgvector operator appears in domain or application code, so the decision stays reversible. Revisit when
retrieval quality is actually measured and the measurement says the index is the limit.

### Why is the API a single process?

Because two API processes could double-claim the same ingestion job or Evaluation case. The rejected
alternative was running multiple workers behind Compose and trusting the claim query to be atomic enough.
Making that safe needs real leasing with expiry, idempotent processing, and a recovery story for a worker
that dies mid-claim — none of which exists, and shipping the configuration without it would convert a
documented limitation into a rare, hard-to-reproduce bug. The accepted cost is no horizontal scaling,
reported as `NOT TESTED` rather than implied by the presence of containers.

### Why does Mock exist in the product and not only in tests?

The rejected alternative was making a real provider the default experience and confining Mock to the test
suite. That would have meant the demo needs a key and a bill, the offline and browser suites need network
access, and the runtime port would have stayed implicit because nothing else implemented it. Keeping Mock
as the default is what makes the whole product reproducible from a clean clone, and it forced the runtime
contract to be explicit early. The accepted cost is that the default demo cannot prove real provider
behavior, and that gap is reported rather than hidden: DeepSeek has real validation, OpenAI is
**NOT TESTED**.

### Why no authentication in v1?

The rejected alternative was basic auth or a single static token, to look more complete. Half-authentication
is worse than none: it invites exposure while leaving session handling, credential storage, per-resource
authorization, and tenancy unsolved, and it would let the project claim a security posture it does not
have. Instead, Web and API bind to loopback, PostgreSQL is internal-only, the frontend never receives
database or provider credentials, and the limitation is stated plainly. This is the first thing to revisit
in a v2, because it gates everything else.

### Why not let SDK types flow through the system?

Spreading the provider SDK's response and event objects would have removed a translation layer and made
the first integration faster. It would also have made the SDK the product's data model: persisted events
would change shape when the SDK changed, the Mock would have to imitate SDK internals, and eventually the
frontend or the database would depend on provider-specific fields. Instead the SDK stops at the adapter and
only normalized application events are persisted. The accepted cost is a real translation layer plus
contract tests to keep two runtime implementations honest. Revisit only if the translation cost starts
exceeding the value of provider independence, which is not the case here.

## Engineering stories (STAR)

Use these when asked "tell me about a hard problem you solved". Each one is a real commit in this
repository.

### Story 1 — Failed re-ingestion leaked dirty data into retrieval

- **Situation.** Knowledge documents could be re-ingested to replace their content. Retrieval selected
  chunks by knowledge base and document identity.
- **Task.** Make a replacement ingestion safe when it fails partway, without losing the previously working
  version.
- **Action.** Introduced ingestion generations (`515d27f`): chunks stage against their owning job with a
  disjoint negative index range, activation deletes the prior generation and its vectors, normalizes the
  index, and marks the job completed in one transaction. Then hardened failure handling (`224bd9c`):
  activation became idempotent, failure became terminal while preserving the previous generation,
  per-document concurrency was serialized, and every retrieval boundary was made to require a `completed`
  job. A startup migration backfilled generations for pre-existing chunks only when unambiguous.
- **Result.** 27 RAG tests cover the invariant, nine of them locking generation consistency directly,
  including a test that hand-inserts orphaned vectors and proves all four retrieval boundaries ignore them.

### Story 2 — Durable Memory raced with Memory being disabled

- **Situation.** Memory finalization read the Agent's memory-enabled setting and then wrote a fact. A
  concurrent settings change could produce duplicate facts or write after the user disabled Memory.
- **Task.** Make the outcome deterministic under both interleavings, on two different databases.
- **Action.** The first fix (`32d0a92`) put the policy gate, the write, its event, and Run completion in a
  single transaction. Recognizing that atomicity alone does not prevent interleaving, the second fix
  (`cdb3773`) routed both the settings change and finalization through a serialized transaction that locks
  the Agent-owned row —`BEGIN IMMEDIATE` on SQLite, `SELECT ... FOR UPDATE` on PostgreSQL — and made
  unsupported dialects raise. Finalization now reads the flag inside the lock.
- **Result.** Both orderings are asserted as fixed behavior in offline tests, and a PostgreSQL test drives
  two real interleavings with connection-level barriers. The cost is a per-Agent write lock on
  finalization, which is the right trade at single-user scale and is documented as such.

### Story 3 — An OpenAI-compatible endpoint is not an OpenAI provider

- **Situation.** DeepSeek exposes an OpenAI-compatible Chat Completions API, and the tempting shortcut was
  to reuse the OpenAI path with a different base URL.
- **Task.** Add real DeepSeek support without corrupting provider identity in traces or sending
  Responses-only settings to an endpoint that does not implement them.
- **Action.** Added an explicit provider resolver (`f568029`) so provider identity, API style, credentials,
  base URL validation, transport bounds, and capability defaults are separate. DeepSeek gets its own key,
  a validated official origin, a streamed Chat Completions model, and explicitly disabled thinking mode
  rather than mechanically mapped reasoning settings. Events persist `provider=deepseek` with API style and
  normalized usage, and there is no silent fallback in either direction.
- **Result.** Offline contract tests plus an opt-in live suite covering stream and usage, model-selected
  Calculator through the application executor, RAG with completed ingestion and citations, Memory
  retrieval, and an Evaluation case. Live validation runs from a manual protected workflow and is never a
  pull request gate.

### Story 4 — A reachable API is not a healthy API

- **Situation.** The Studio connection indicator could show "connected" while the backend was returning a
  server error.
- **Task.** Find the root cause rather than papering over the symptom with a retry.
- **Action.** The health decision in `apps/web/lib/api.ts` read
  `body?.detail || response.status < 500 ? "connected" : "offline"`. Operator precedence made the ternary
  bind to the whole `||` expression, so any truthy `detail` string won and reported "connected" even for a
  `5xx`. The fix (`e472d84`) reduced it to `response.status < 500 ? "connected" : "offline"` and the
  combined browser flow that exposed it became a permanent regression scenario.
- **Result.** Health is now derived from the request contract instead of transport reachability, and a
  recovery state is only shown after a real success. This is a good story about reading a one-line
  expression carefully instead of adding defensive code around it.

### Story 5 — Proving a row-lock claim without a database

- **Situation.** The Memory serialization design claimed PostgreSQL `FOR UPDATE` semantics, but the offline
  suite has no PostgreSQL.
- **Task.** Avoid the two bad options: claiming behavior that was never executed, or skipping the claim
  entirely until CI runs against a real database.
- **Action.** Split the evidence. Offline, `test_postgresql_agent_memory_ownership_uses_row_lock` compiles
  the statement against the PostgreSQL dialect and asserts it ends in `FOR UPDATE` — a compilation claim,
  clearly labelled as such. Against a real database,
  `test_postgresql_memory_row_locks_prove_both_orderings` drives both interleavings with connection-level
  barriers.
- **Result.** The offline suite stays fast and key-free while the strong claim is carried by a real
  database test. The general lesson is to label the strength of each piece of evidence rather than letting
  a weak test imply a strong guarantee.

### Story 6 — Naming delivery precisely

- **Situation.** Container validation passed, and it would have been easy to describe the project as
  deployed or production-ready.
- **Task.** Choose a definition that is true and still useful.
- **Action.** Defined `DELIVERY READY` narrowly (`acf5edf`, `a65c429`): this commit's production images
  built and its disposable Compose runtime passed the documented smoke and E2E checks. The workflow pushes
  no registry image and deploys no target, and a cleanup failure removes the readiness artifact instead of
  reporting success.
- **Result.** The project can point at real delivery evidence without overstating it, and the same
  discipline is applied to provider status, performance numbers, and the limitations section. Being able to
  say "here is what this does not prove" turned out to be the most useful habit in the whole project.
