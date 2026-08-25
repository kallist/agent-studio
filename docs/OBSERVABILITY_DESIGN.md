# Observability / Trace v1

## Goals

Agent Studio owns a stable observability layer for debugging runs, inspecting runtime, tool,
knowledge, and memory behavior, and supplying immutable evidence to later evaluation work. The
layer reports only values measured or persisted by the application.

## Non-goals

This version does not implement evaluation scoring, OpenTelemetry export, distributed tracing,
Prometheus, Grafana, Elasticsearch, provider dashboards, authentication, or a second trace store.

## Event model

`AgentEvent` is the application contract. It has a stable identity, run identity, monotonically
assigned sequence, timestamp, open-ended event name, safe payload, and optional `step_index`,
`tool_call_id`, `duration_ms`, and token usage. Known names are documented, but unknown future
names remain persistable and pass through the generic `agent.event` SSE channel.

The persistence adapter stores the extended event in the existing `run_events.payload_json`
column as a versioned application envelope. Legacy payload-only rows remain readable. No OpenAI
Agents SDK object or provider response is stored or returned by the API.

## Trace flow

```text
AgentLoop / application workflow
  -> application AgentEvent
  -> correlation and measured boundaries
  -> recursive redaction
  -> RunEvent persistence
  -> read-time aggregation
  -> REST and generic SSE envelope
  -> Studio metrics and trace UI
```

Persistence happens before live publication. The exact safe event published over SSE is the event
intended for persistence; the repository repeats sanitization as defense in depth.

## Correlation

Every executed tool decision uses the application-generated `ToolCall.call_id`. `tool.selected`,
`tool.started`, and `tool.completed` or `tool.failed` expose the same `tool_call_id` and
`step_index`. Sequence is assigned once by `AgentService`, so correlation never depends on visual
adjacency. `knowledge_search` follows the same tool contract.

## Metrics

Run metrics include status, termination reason, lifecycle timestamps, event and step counts, tool
call totals and outcomes, safe error information, and optional usage. Tool observations include
input, safe output, error, timestamps, correlation, step, and duration. Dashboard counts, success
rate, average run duration, and recent runs are derived from backend persistence.

## Latency

Durations use milliseconds and are non-negative. Tool, model, memory retrieval, and run terminal
boundaries use monotonic clocks while executing. Read-time aggregation uses a measured
`duration_ms` when present and falls back to persisted start/end timestamps only when both exist.
Atomic memory finalization extends the terminal measurement and persists `memory.written` before a
later-timestamped `run.completed`. An incomplete boundary returns `null`; it never invents zero
latency.

## Token usage semantics

Token fields are optional. Mock Runtime does not have real model usage, so `input_tokens`,
`output_tokens`, and `total_tokens` are always unavailable (`null`). String-length estimates are
forbidden. OpenAI usage may be translated at the SDK adapter only when a stable, real SDK value is
available; this version leaves it unavailable rather than guessing.

## Redaction

Structured values are recursively redacted by sensitive key before persistence and publication.
Covered keys include authorization, API keys, access and refresh tokens, passwords, secrets,
cookies, and set-cookie, including common separator/case variants. Lists and nested objects are
handled. Free-form text is changed only for explicit `label=value` or `label: value` secret forms,
so ordinary prose containing the word “token” remains intact.

Knowledge trace output stores query, mode, top-k, result count, citation/provenance metadata, and
scores. Retrieved chunk bodies are not copied into trace storage. Existing tool output validation
and size limits remain the upstream bound.

## Error handling

Terminal failure events contain a normalized category, bounded safe summary, status, timestamp,
and termination reason when available. Python stack traces remain server-log-only. Cancellation is
a separate terminal state and event; it is not counted as failure or success.

## Persistence and source of truth

`runs` and ordered `run_events` are the only source of truth. `RunObservability` and dashboard
telemetry are read-time projections. There is no separately persisted `RunMetrics` copy that can
drift. Dashboard aggregation groups global status counts from `runs`; average duration and recent
details use the bounded 30 most recent runs and their events. It never loads the complete event
table or runs on the event-write path.

## SSE

Typed SSE event names remain for existing consumers. Every event is also mirrored as
`agent.event`, including unknown names, and clients deduplicate by `event_id` while ordering by
sequence.

## UI

Run Detail shows status, real duration, steps, events, tool totals/failures, and token availability.
Trace filters cover lifecycle, runtime/LLM, tools, knowledge/RAG, memory, and errors without changing
stored data. Unknown events remain visible under All through a generic detail renderer. Dashboard
telemetry comes from the backend and shows unavailable values instead of misleading zeroes.

## Testing

Deterministic tests use controlled event timestamps for aggregation and application fixtures for
completed, failed, cancelled, RAG, memory, redaction, usage-unavailable, SSE-forward-compatibility,
and UI filtering. No latency assertion depends on sleeping or a minimum wall-clock duration.

## Current limitations

- Real OpenAI network usage translation is not validated in the default no-key test path. The
  explicit `real_openai` suite verifies request count, token aggregation, model, stream consumption,
  and tool-call correlation when locally opted in.
- Live PostgreSQL/pgvector Observability is validated through persisted Calculator, RAG, Memory,
  and Evaluation workflows, including tool correlation, durations, Dashboard isolation, and
  redaction before persistence. Production-scale analytics performance remains untested.
- Metrics are read-time projections suitable for the current data volume, not a large analytics
  warehouse.
- Trace JSON export is deferred because it adds no debugging capability beyond the redacted REST
  contract in this version.

## Future OpenTelemetry and metrics integration

A later adapter may export these application IDs, correlations, durations, and safe attributes to
OpenTelemetry or a metrics backend. Export must remain downstream of this contract, preserve
redaction, and must not replace Run/RunEvent as product evidence or leak provider SDK types.

## Synthetic performance baseline

Task 13 performance evidence is separate from runtime Observability. Observability projects real
persisted Run/RunEvent behavior for debugging; the performance suite executes controlled synthetic
work against a disposable test database and compares broad engineering thresholds. Its p50/p95 and
throughput are regression signals, not production telemetry, capacity, or an SLA. The suite reuses
real product paths but never writes benchmark results into Run/RunEvent or auto-updates its baseline.
