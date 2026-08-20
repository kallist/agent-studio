# Agent Evaluation Framework v1

## 1. Goals

Agent Studio owns a deterministic, offline, reproducible regression framework for final answers,
tool selection, retrieval, citations, durable Memory participation, bounded steps, and measured
latency. Evaluation answers whether a real agent execution satisfied explicit expectations.

The verified no-key path uses `MockRuntime`. Evaluation never fabricates a Run, RunEvent, tool
call, retrieval result, citation, Memory event, duration, or score.

## 2. Non-goals

v1 does not implement LLM-as-a-Judge, OpenAI Evals API, RAGAS, TruLens, ARES, arbitrary user
graders, prompt optimization, human annotation, multi-agent/MCP evaluation, online A/B testing,
production sampling, reinforcement learning, fine-tuning, or a benchmark cloud service.

## 3. Domain model

```text
EvaluationSuite (mutable definition, monotonic revision)
  -> EvaluationCase[] (structured input, setup, graders)
  -> EvaluationRun (immutable Suite + Agent snapshots)
       -> EvaluationCaseResult[]
            -> actual Run reference
            -> GraderResult[]
```

Evaluation tables are separate from RunEvent. RunEvent describes what happened; Evaluation
describes whether the persisted behavior met a stated expectation.

## 4. Suite and Case

A Suite has an owning source Agent, name, description, revision, timestamps, and ordered Cases.
Case changes increment the Suite revision. Delete is soft so historical EvaluationRuns retain
lineage.

A Case contains a bounded input, enabled flag, one or more structured grader configurations, and
an optional allowlisted setup. v1 setup supports only evaluation-scoped durable Memory records,
and every seed passes the same `MemoryPolicy` content gate as normal durable writes.
It cannot execute Python, shell, SQL, regular expressions, imports, or file paths.

## 5. Grader contract

`DeterministicGrader.grade(config, context)` receives one already-loaded context containing the
persisted `Run`, ordered `RunEvent` list, and Task 07 `RunObservability`. It returns:

- grader type and whether it is required;
- outcome `pass`, `fail`, or `error`;
- binary score `1` or `0`, or `null` when the grader cannot decide;
- bounded reason;
- structured expected and actual values;
- event evidence references containing Run/Event identity and sequence.

No grader calls a model or performs its own database query.

## 6. Built-in deterministic graders

- `run_status`: compares the actual terminal Run state, defaulting to `completed`.
- `final_output_non_empty`: trims only to decide whether output is empty.
- `exact_match`: trims leading/trailing whitespace and applies configured case sensitivity.
- `contains`: deterministic substring matching with configured case sensitivity.
- `tool_selected` / `tool_not_selected`: read real `tool.selected` events.
- `retrieval_hit`: reads real `knowledge_search` result provenance.
- `citation`: verifies citation presence and optional source/document identity from provenance.
- `memory_retrieved`: requires a positive real `memory.retrieved` event.
- `max_steps`: compares Task 07 `step_count` with an inclusive maximum.
- `max_duration`: compares measured `duration_ms` with an inclusive maximum; unavailable duration
  is a grader `error`, never PASS.

Binary graders have defined score `pass=1`, `fail=0`. v1 does not invent fractional quality
scores.

## 7. Execution flow

```text
POST Suite Run -> 202 queued -> bounded LocalEvaluationWorker
  -> each enabled Case in snapshot order
  -> create hidden evaluation-owned Agent clone
  -> seed optional Memory through MemoryStore
  -> AgentService.create_run(run_kind=evaluation)
  -> real Runtime / Tool / RAG / Memory / RunEvent path
  -> load Run + Events + Observability once
  -> execute all configured graders
  -> persist CaseResult + GraderResults
  -> update real progress and aggregate
```

The worker defaults to concurrency one. Fifty Cases do not create fifty unbounded concurrent
Agent Runs.

## 8. Async job semantics

EvaluationRun states are `queued`, `running`, `completed`, `failed`, and `cancelled`. Progress is
the count of terminal CaseResults and changes only after a Case reaches PASS, FAIL, or ERROR.

A business FAIL does not fail the worker: the EvaluationRun completes with failed Cases. Only an
escaped evaluation infrastructure failure makes the EvaluationRun `failed`.

The start endpoint supports a validated `Idempotency-Key`. Reusing a key returns the existing
EvaluationRun, and a Suite with an active queued/running run returns that run. The UI also disables
the start action while its request is active.

## 9. PASS, FAIL, and ERROR

- PASS: every required grader passed.
- FAIL: the real Agent Run completed its product path, but at least one required grader failed.
- ERROR: a required grader could not decide or Case execution infrastructure could not run.

An incorrect answer such as actual `5192` versus expected `9999` is FAIL, not ERROR. Optional
grader errors do not change an otherwise passing Case.

## 10. Aggregation

`total_cases` is the enabled Case count in the immutable Suite snapshot. `completed_cases` is the
number of terminal CaseResults. The Suite pass rate is:

```text
passed_cases / completed_cases
```

ERROR is therefore in the denominator. Zero completed Cases yields `null`/N/A, not 100% or 0%.
Average duration uses only available real durations. p95 uses the nearest-rank definition:
`sorted[ceil(0.95 * n) - 1]`; zero available durations yields N/A.

Grader-level rates exclude grader ERROR from their denominator because no pass/fail decision was
available. The API and UI consume the same persisted aggregate contract.

## 11. Source of truth

`Run` plus ordered `RunEvent` remains the only source of truth for agent behavior. Evaluation
persists definitions, snapshots, references, grader facts, and allowed aggregates. It does not copy
the Trace or create a second event viewer. `EvaluationCaseResult.run_id` links to the existing Run
Detail and Trace UI.

## 12. Reproducibility

Every EvaluationRun stores the Suite revision, canonical Suite snapshot, per-Case definition hash,
Agent snapshot, runtime limits, and canonical Agent configuration hash. Later Suite/Case/Agent
edits do not mutate prior snapshots or grader results.

## 13. Agent snapshot and version

Agent definitions do not yet have a first-class version table. v1 therefore snapshots only the
relevant immutable execution configuration: source Agent identity, instructions, runtime/provider
mode, model, enabled tools, attached Knowledge Bases, Memory enabled state, creation timestamp, and
current application-owned runtime limits. The SHA-256 `config_hash` detects configuration drift.

## 14. Evaluation isolation

Each Case creates a hidden `kind=evaluation` Agent clone. The clone uses the same runtime mode,
instructions, tools, and read-only Knowledge Base bindings as the source Agent. Its actual Run is
persisted with `run_kind=evaluation`. Hidden clones are not returned by the normal Agents list.

Each Case and each EvaluationRun receives a new clone, so setup or runtime writes cannot leak to a
later Case. Clones remain persisted because historical Runs retain their foreign-key and trace
lineage.

## 15. Memory isolation

Evaluation Memory setup writes through the real `MemoryStore` under the Case's unique evaluation
Agent ID. Retrieval and `memory.retrieved` use the normal `MemoryRetriever`, policy, and event path.
Runtime finalization may write only into the same evaluation Agent namespace. The source Agent's
durable Memory is never read or mutated by the isolated Case, and cleanup never deletes normal
Memory.

The existing serialized Memory settings/finalization transaction remains unchanged. Evaluation
does not add a second commit path and therefore preserves the disable/finalization ordering and
Memory/event/terminal atomicity invariants.

## 16. RAG behavior

Evaluation reuses source Agent Knowledge Base bindings as read-only dependencies. It does not
ingest or alter Knowledge data during Case execution. The normal `knowledge_search` tool still
enforces application-owned scope, completed-only retrieval, generation staging, failed-ingestion
isolation, and citation provenance. Retrieval and citation graders read only normalized tool
evidence from the real Run.

## 17. Observability integration

Evaluation Runs execute through `AgentService` and the same bounded runtime. They retain complete
RunEvent persistence, tool call IDs, step indices, latency, redaction, generic SSE support, and
Task 07 Observability. Graders load Run, Events, and Observability once per Case, preventing one
database scan per grader.

## 18. Dashboard isolation

`Run.run_kind` distinguishes `normal` and `evaluation`. Normal Dashboard list and status-count
queries explicitly select `normal`; evaluation traffic cannot inflate normal totals, success rate,
average duration, or recent runs. Evaluation metrics are shown only on Evaluation surfaces. Viewing
an Evaluation trace also does not add it to the frontend's normal recent-run cache.

## 19. Security

All schemas enforce length/count bounds and typed fields. There is no executable grader or setup
payload. Idempotency keys use a small character allowlist. Evaluation reasons, expected/actual
values, and evidence pass through Task 07 recursive redaction before persistence. Exceptions shown
to a Case result are bounded by category; Python tracebacks stay in server logs.

Inputs, expected values, RAG content, and Memory content remain untrusted data. Evaluation does not
promote them into system instructions. HTTP/File/Tool security boundaries remain unchanged.
Definitions or Agent configurations containing labelled secret values are rejected with 422 rather
than silently rewritten before execution. Graders decide against the real output; persisted grader
data and the Evaluation result API expose only the existing redacted representation.

## 20. Testing

Backend tests cover every grader boundary, PASS/FAIL/ERROR, aggregate denominators, p95, persistence,
idempotency, snapshots, async completion, infrastructure Case ERROR, cancellation, Calculator
`5192`, intentional mismatch, RAG provenance, Memory retrieval/isolation, and Dashboard isolation.
Frontend tests cover Suite list/zero state, dynamic grader fields, N/A metrics, summary math,
PASS/FAIL/ERROR filters, Case detail, reason, and trace action. Playwright covers the integrated
browser workflows with MockRuntime.

## 21. Limitations

- The local Evaluation worker is process-local and intended for one API process.
- Startup recovery requeues queued/running EvaluationRuns and marks an interrupted in-flight Case
  ERROR; any referenced non-terminal Agent Run receives a persisted restart failure event.
- Hidden evaluation Agent clones are retained for lineage and currently have no retention policy.
- There is no baseline-comparison UI in v1.
- Real OpenAI evaluation is NOT TESTED.
- Live PostgreSQL/pgvector evaluation is NOT TESTED unless separately reported.

## 22. Future LLM-as-Judge and OpenAI Evals integration

A future grader adapter may add LLM-as-a-Judge or OpenAI Evals, but it must declare nondeterminism,
provider/model/version, prompt/configuration, cost, retry policy, and unavailable/error semantics.
It must remain downstream of the same immutable Run/RunEvent evidence, redaction, snapshots,
isolation, and application-owned PASS/FAIL/ERROR aggregation.
