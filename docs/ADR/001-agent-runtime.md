# ADR-001: Hybrid agent runtime

- Status: Accepted
- Date: 2026-08-13
- Decision owners: Agent Studio maintainers

## Context

Agent Studio must demonstrate a real agent loop, tools, memory, traces, knowledge retrieval, and evaluation while remaining testable without an API key and portable enough to avoid embedding one provider SDK throughout the product.

Current official OpenAI documentation distinguishes direct Responses API ownership from Agents SDK ownership: use Responses when the application should own the loop, and use Agents SDK when the SDK should manage recurring tool calls, branching, sessions, tracing, guardrails, and resumable approvals. The documentation also states that an SDK-based server can still own deployment, tool implementations, storage, and approval decisions.

Sources reviewed on 2026-08-13:

- https://developers.openai.com/api/docs/guides/agents
- https://developers.openai.com/api/docs/guides/agents/running-agents
- https://developers.openai.com/api/docs/guides/agents/results
- https://developers.openai.com/api/docs/guides/agents/integrations-observability
- https://developers.openai.com/api/docs/guides/agent-evals

## Options considered

### Option A: Custom runtime

Implement the model/tool loop, tool routing, continuation state, approvals, streaming, and trace lifecycle directly, probably on the Responses API.

- Learning and interview value: highest visibility into loop mechanics.
- Control and portability: highest, because application types own everything.
- Complexity and test burden: highest; subtle loop, streaming, state, and approval behavior becomes project code.
- Tracing/tools: fully customizable, but must be designed, implemented, and maintained.
- Risk: baseline work expands into rebuilding infrastructure before Agent Studio can study actual agent-product problems.

### Option B: Agents SDK as the application architecture

Use SDK agents, sessions, results, traces, and tool abstractions directly throughout services and persistence.

- Learning and delivery speed: fast path to real runs, tools, guardrails, and traces.
- Complexity: low initially.
- Control and portability: weak if SDK types leak into repositories, API schemas, memory, and product traces.
- Testing: SDK behavior can be exercised, but deterministic no-key paths and application-owned event semantics become harder if every layer depends on the SDK.
- Risk: Agent Studio becomes a thin SDK console rather than a platform with durable domain boundaries.

### Option C: Hybrid

Use the Agents SDK inside an `AgentsSdkRuntime` adapter for the loop, tool-call lifecycle, streaming, guardrails, approvals, and provider trace correlation. Keep application persistence, evaluation, knowledge retrieval, durable memory policy, tool policy, and the product trace/event model behind Agent Studio ports.

- Learning and interview value: demonstrates informed reuse plus explicit ports, adapters, deterministic tests, and observability design.
- Complexity: moderate and focused on meaningful translation boundaries instead of reimplementing the entire loop.
- Control: application contracts and stored data remain ours; SDK behavior is isolated.
- Testing: `MockProvider` and deterministic runtime fixtures exercise use cases without an API key; SDK contract tests cover only the adapter.
- Tracing: SDK tracing supports debugging, while `TraceStore` supplies stable product events and UI queries.
- Memory: SDK session mechanics may support a live run, but `MemoryStore` owns durable product memory and policy.
- Tools: SDK function/tool support is used inside the adapter; `ToolRegistry` and `ToolExecutor` retain validation, permissions, timeouts, and audit rules.
- Portability: a future custom or alternative runtime can implement `AgentRuntime` without rewriting services, repositories, or APIs.

## Decision

Choose **Option C: Hybrid**.

The initial real runtime will use the Python OpenAI Agents SDK behind `AgentRuntime`. No SDK type may cross into FastAPI schemas, domain entities, repositories, `MemoryStore`, `KnowledgeStore`, `VectorStore`, or persisted trace events. `OpenAIProvider` is the real provider adapter; `MockProvider` is deterministic and is the default for tests and the calculator demo when no API key is configured.

Agent Studio will own:

- agent/version persistence;
- run status and idempotency;
- tool registration policy and execution controls;
- durable memory policy;
- knowledge ingestion and retrieval abstractions;
- evaluation cases and results;
- normalized trace/event persistence and the trace UI.

The Agents SDK will initially own inside the adapter:

- the model invocation and structured-output decoding used by each bounded runtime step;
- handoff/orchestration primitives when a demonstrated use case requires them;
- streaming and resumable SDK run state;
- guardrail/approval mechanics;
- provider trace correlation and SDK diagnostics.

## Runtime hardening refinement (2026-08-13)

The first vertical slice exposed a reproducible policy gap: the SDK-managed loop did not expose
application-owned `AgentState`, bounded `AgentStep` persistence, cross-provider duplicate-call
protection, or a shared cancellation path for the Mock and OpenAI runtimes. Those controls are core
Agent Studio product behavior, not provider behavior.

The hybrid decision remains accepted. The implementation boundary is refined as follows:

- `AgentLoop`, inside the runtime adapter layer, owns the outer `max_steps` loop, total timeout,
  cancellation, context budget, typed decision validation, tool policy, and normalized step events.
- `AgentsSdkRuntime` remains the only Agents SDK adapter. It asks the SDK for one typed
  `AgentDecision` per application step with `max_turns=1`; SDK types still do not cross the runtime
  boundary.
- `ToolRegistry` and `ToolExecutor` remain application-owned and enforce schemas, permissions,
  timeouts, output limits, and structured failures.
- `MockRuntime` and `AgentsSdkRuntime` share the same `AgentLoop`, so deterministic tests cover the
  production state machine rather than a separate rule-only path.

This refinement does not replace the hybrid architecture with a provider-wide custom runtime. It
moves only product policy and observable state to the application-owned outer loop; the Agents SDK
continues to own OpenAI model invocation, typed output integration, provider tracing, and SDK error
normalization inside its adapter.

## Consequences

- The first vertical slice must define small application-owned request, result, and event contracts before adding the SDK dependency.
- The adapter adds translation work, but that work is a deliberate portability and test seam.
- The project must not duplicate every SDK trace internally. Persist only the normalized events needed for product behavior, auditing, evaluation, and debugging.
- SDK sessions are not automatically equivalent to Agent Studio memory. A later ADR must define durable memory policy after a real use case exists.
- If the SDK cannot support a required workflow without leaking provider details, implement a second `AgentRuntime` adapter or revise this ADR with measured evidence.

## Validation plan

The first vertical slice should prove both paths:

1. A deterministic calculator run using `MockProvider`, with tool calls and stored trace events, without `OPENAI_API_KEY`.
2. An opt-in OpenAI-backed run through `AgentsSdkRuntime`, guarded by the credential gate and excluded from default tests.

Contract tests must assert that both produce the same application-level run/event shapes.
