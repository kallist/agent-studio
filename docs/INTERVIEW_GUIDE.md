# Agent Studio interview guide

## 30-second pitch

Agent Studio is a development and debugging platform for AI Agents. Instead of hiding behavior behind a chat UI, it owns a bounded execution loop and persists tool calls, RAG citations, Memory events, and terminal state so each Run can be traced and deterministically evaluated. The default demo is offline Mock; DeepSeek is real-tested; PostgreSQL/pgvector and a production-like Docker stack make the engineering path concrete.

## Two-minute pitch

The browser talks to Next.js and FastAPI. `AgentService` creates a persisted Run, then an application-owned `AgentLoop` asks a provider for one typed decision per bounded step. A provider can return a final answer or a captured tool request; only `ToolExecutor` can validate and execute it. Knowledge retrieval and durable Memory are assembled as untrusted context. Every lifecycle transition is persisted as an ordered RunEvent before the UI projects it into live trace and dashboard views. Evaluation clones the Agent snapshot, executes real isolated Runs, and applies deterministic graders with PASS, FAIL, or ERROR. The recommended Docker path uses PostgreSQL 17/pgvector, non-root images, internal DB networking, generated runtime secrets, and CI gates. The deliberate v1 boundary excludes Auth, multi-tenancy, distributed workers, Kubernetes, and live OpenAI claims.

## Five-minute architecture walk-through

1. **Web boundary:** Next.js provides Agent Builder, Playground, Knowledge, Memory, Run Detail, Dashboard, and Evaluations; it never receives database/provider credentials.
2. **API workflow:** thin FastAPI routes call application services. The service persists pending state and invokes a stable `AgentRuntime` port.
3. **Execution:** `AgentLoop` owns bounds, cancellation, retries, context limits, duplicate-call policy, and typed termination. Mock and the Agents SDK adapter share this contract.
4. **Capabilities:** server-owned ToolRegistry/ToolExecutor controls tools; RAG exposes completed generations and citations; Memory applies Agent-scoped policy and transaction ordering.
5. **Lineage:** Run plus ordered RunEvent is the source of truth. Live SSE, Run Detail, Dashboard, and Evaluation are projections.
6. **Persistence and delivery:** SQLite is the local fallback; Docker uses PostgreSQL/pgvector. CI separately validates code, real DB behavior, browser flows, containers, reliability, performance, and fresh-stack delivery.

## Questions and answers

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

### 15. Why is Mock usage N/A instead of zero?

**Short:** No provider request occurred.

**Deep:** Zero tokens would falsely imply a metered call that consumed none; nullable usage accurately distinguishes absent measurement from measured zero.

### 16. Why is DeepSeek not called an OpenAI provider?

**Short:** Compatible client syntax does not erase provider identity or API semantics.

**Deep:** Events persist `provider=deepseek` and Chat Completions style. Credentials, base URL validation, capability differences, defaults, and tracing policy remain separate.

### 17. Why only one API process in Docker?

**Short:** Ingestion and Evaluation workers are currently application-local.

**Deep:** Multiprocess operation could duplicate worker claims and needs a distributed coordination design. v1 keeps one process and labels horizontal operation NOT TESTED.

### 18. Why does CI not call DeepSeek automatically?

**Short:** Default gates must be deterministic, secret-free, and non-billable.

**Deep:** Real DeepSeek uses a protected manual Environment workflow; ordinary PR/main workflows clear keys and run Mock. This separates merge confidence from provider availability/cost.

### 19. Why are performance thresholds wide?

**Short:** GitHub-hosted runners are noisy; the gate targets catastrophic regressions, not fake precision.

**Deep:** A reviewed baseline records p50/p95/throughput; 1.5x is report-only and 4x/quarter-throughput is blocking. Functional failures always block and baseline changes require review.

### 20. Why no Auth, Redis, or Kubernetes in v1?

**Short:** They do not improve the core proof that Agent behavior is observable and reproducible.

**Deep:** Adding shared-service exposure before Auth/tenancy, or distributed infrastructure before worker semantics, would widen risk and dilute correctness. The single-user local boundary is explicit.

## Failure stories

### Failed-generation leakage

**Problem:** re-ingestion could expose replacement chunks before the job was safely complete. **Root cause:** retrieval keyed only by document identity. **Fix:** generation-scoped staging plus atomic completed activation and completed-only queries. **Lesson:** async job status must participate in data visibility.

### Memory concurrency race

**Problem:** simultaneous Runs/settings changes could produce duplicate or policy-inconsistent Memory. **Root cause:** read/decide/write was not one serialized transaction. **Fix:** adapter-specific serialized transactions and deterministic interleaving tests, including PostgreSQL row locks. **Lesson:** policy guarantees require database ordering evidence.

### False connected UI

**Problem:** a structured backend 5xx could leave the client looking connected. **Root cause:** transport reachability was conflated with application health. **Fix:** report API failure on non-2xx responses and prove recovery after a real success. **Lesson:** health state belongs to the request contract, not TCP alone.

### DeepSeek compatibility boundary

**Problem:** OpenAI-compatible syntax could tempt the system to mislabel DeepSeek or send Responses-only settings. **Root cause:** client compatibility is broader than provider capability compatibility. **Fix:** explicit provider resolver, Chat Completions model, normalized identity, base URL validation, and separate real tests. **Lesson:** compatibility layers need provider-specific contracts.

### Delivery evidence vs deployment

**Problem:** successful container tests can be overstated as deployment. **Root cause:** ambiguous “CD” terminology. **Fix:** define DELIVERY READY as built-and-validated SHA evidence with no registry push/public target. **Lesson:** name operational claims precisely.

## Tradeoffs

- **No multi-agent:** v1 proves one Agent's lifecycle and lineage first.
- **No Redis/distributed workers:** persisted local workers are sufficient for the bounded local product; distribution needs explicit leasing and idempotency design.
- **No Kubernetes:** the app has no public-service Auth/tenancy/ingress contract to deploy safely.
- **No Auth:** v1 is deliberately loopback-only and single-user; this limitation blocks public/shared exposure.
