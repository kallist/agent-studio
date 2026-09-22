# Agent Run lifecycle

This document follows one normal Agent Run from the HTTP request to its terminal record. It describes
the current implementation; `docs/ARCHITECTURE.md` covers the boundaries, and `docs/V1_STATUS.md`
tracks which parts are validated.

A Run is created by `POST /api/agents/{agent_id}/runs`, which returns the persisted Run immediately
while execution continues. Every lifecycle transition below is written as an ordered `RunEvent` before
it is published to the live stream, so a client that connects late still reads the same history from
persistence.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant UI as Playground / Client
    participant API as FastAPI route
    participant SVC as AgentService
    participant REPO as Repositories
    participant LOOP as AgentLoop
    participant PRV as LLMProvider
    participant TOOL as ToolExecutor
    participant DB as PostgreSQL / SQLite

    UI->>API: POST /api/agents/{id}/runs
    API->>SVC: start_run(input)
    SVC->>REPO: create Run (status=pending, run_kind=normal)
    REPO->>DB: INSERT Run
    SVC-->>API: Run view (202-style immediate response)
    API-->>UI: Run created

    SVC->>REPO: persist run.started
    REPO->>DB: INSERT RunEvent sequence 1
    SVC->>REPO: status=running
    SVC->>SVC: assemble bounded context (instructions, Memory, retrieval is tool-driven)
    SVC->>REPO: persist memory.retrieved or memory.retrieval.skipped

    loop every bounded step, up to max_steps
        SVC->>REPO: persist step.started
        LOOP->>REPO: persist llm.started
        LOOP->>PRV: one typed AgentDecision
        PRV-->>LOOP: final answer, or a captured tool request
        alt provider returned invalid structured output
            LOOP->>REPO: persist llm.retrying (bounded by invalid_output_retries)
        else valid decision
            LOOP->>REPO: persist llm.completed (provider, model, api style, usage)
        end
        alt decision is a tool call
            LOOP->>REPO: persist tool.selected
            LOOP->>TOOL: execute validated call
            TOOL->>TOOL: name, schema, permission, timeout, output limit, duplicate policy
            TOOL->>REPO: persist tool.started, then tool.completed or tool.failed
            Note over LOOP: the ToolResult becomes the next step's observation
        else decision is a final answer
            Note over LOOP: the loop terminates
        end
        LOOP->>REPO: persist step.completed
    end

    LOOP-->>SVC: steps, output, typed TerminationReason, usage
    SVC->>REPO: finalize Run and Memory in one transaction
    REPO->>DB: terminal RunEvent + terminal Run status commit together
    SVC-->>UI: Run detail, live trace, dashboard, Evaluation all read this lineage
```

## Event taxonomy

The known contract is a closed list of 16 event types declared in
`apps/api/app/domain/contracts.py`. The persisted `type` column stays open so a future application event
still survives persistence, SSE, and generic rendering.

| Event | Emitted when |
|---|---|
| `run.started` | The Run is persisted and transitions to `running` |
| `step.started` | A bounded loop step begins |
| `llm.started` | One provider decision is requested |
| `llm.retrying` | The provider returned invalid structured output and a bounded retry is attempted |
| `llm.completed` | A valid decision arrived; carries normalized provider, model, API style, and aggregate usage |
| `tool.selected` | The decision selected a tool, before validation |
| `tool.started` | `ToolExecutor` accepted the call and began execution |
| `tool.completed` | Tool execution produced a valid result |
| `tool.failed` | Tool execution failed with a structured error |
| `step.completed` | The step produced its observation or terminal answer |
| `memory.retrieved` | Agent-scoped Memory entered the context |
| `memory.retrieval.skipped` | Memory retrieval was skipped because the Agent disables it |
| `memory.written` | A durable Memory record was persisted during finalization |
| `run.completed` | The loop terminated normally |
| `run.failed` | The loop terminated with an error, or startup failed a non-terminal Run |
| `run.cancelled` | Cancellation was requested and the terminal transaction committed |

Each persisted event records its Run, a monotonic `sequence` within that Run, its type, and a redacted
JSON payload. Secrets are stripped by `app/observability/redaction.py` before persistence, so the stored
payload and the live stream carry identical safe data.

## Terminal reasons

A typed `TerminationReason` maps onto the terminal Run status, and the terminal event commits in the
same transaction as the status change so a Run cannot be left non-terminal by a partial finalization.

| Termination reason | Meaning |
|---|---|
| `completed` | The model produced a final answer inside the step budget |
| `max_steps` | The loop reached `max_steps` without a final answer |
| `timeout` | The Run exceeded its total `timeout_seconds` budget |
| `cancelled` | Cancellation was requested, including while a provider call was in flight |
| `invalid_output` | The provider repeatedly returned invalid structured output, or selected a disallowed or over-limit tool |
| `provider_error` | The provider raised an error; the message is normalized and does not leak internals |
| `tool_error` | Tool execution failed terminally |

## Execution bounds

Every bound is validated at the contract boundary with explicit ranges, so an Agent cannot be saved with
an unbounded value.

| Bound | Field | Applies to |
|---|---|---|
| Maximum steps | `max_steps` | Total loop iterations per Run |
| Total time | `timeout_seconds` | The whole Run, including in-flight provider calls |
| Cancellation | `CancellationToken` | Checked between and during provider calls |
| Invalid-output retries | `invalid_output_retries` | Structured-output validation failures only |
| Context size | `max_context_chars` | Serialized context sent to the provider |
| Decision size | `max_decision_chars` | A single provider decision |
| Repeated tool use | `max_calls_per_tool` | Per tool, per Run, including calls with changed arguments |

An oversized base context is rejected before the provider is called at all, and a provider that selects
a tool the Agent does not have enabled is rejected before any execution begins.

## Restart behavior

- Normal Agent Runs are **not resumed**. Startup deterministically fails persisted `pending` and
  `running` Runs with the `process_restart` category, so a Run cannot stay stuck forever.
- Knowledge ingestion is different: startup requeues queued or abandoned `processing` jobs, and because
  staged chunks are generation-scoped, a restart cannot expose a partial replacement.
- Evaluation is different again: startup marks an interrupted case `ERROR`, fails its non-terminal
  linked Run, and resumes the Evaluation Run.

## Evaluation traffic

An Evaluation case executes a real Run with `run_kind=evaluation` against an evaluation-owned Agent
snapshot. That keeps the graded execution on the same product path a user would exercise, while
dashboard queries project only `run_kind=normal` Runs so regression traffic cannot distort usage and
success metrics.

## Where to read the code

| Concern | Path |
|---|---|
| Run creation, workflow, terminal commit | `apps/api/app/application/service.py` |
| Bounded loop, bounds enforcement, terminal mapping | `apps/api/app/runtime/engine.py` |
| Provider adapters and Mock | `apps/api/app/runtime/providers.py`, `apps/api/app/runtime/agents_sdk.py`, `apps/api/app/runtime/mock.py` |
| Limits and event-type contracts | `apps/api/app/domain/contracts.py` |
| Tool validation and execution | `apps/api/app/tools/registry.py` |
| Terminal transactions, Memory ordering | `apps/api/app/persistence/repositories.py` |
| Event redaction and projection | `apps/api/app/observability/redaction.py`, `apps/api/app/observability/aggregation.py` |
| Lifecycle tests | `apps/api/tests/test_agent_loop.py`, `apps/api/tests/test_reliability.py` |
