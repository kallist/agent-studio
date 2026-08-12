# Memory System v1

## Purpose

Agent Studio owns memory as application data. The runtime may consume a scoped memory snapshot, but OpenAI Agents SDK sessions, provider response IDs, and provider objects are not the durable memory database.

The first version optimizes for correctness and explainability. It deliberately uses deterministic lexical retrieval rather than presenting embeddings or model-generated summaries as implemented behavior.

## Memory categories

| Category | Lifetime | Persistent | v1 behavior |
| --- | --- | --- | --- |
| Conversation Memory | Current run | No | Holds the current run's user message and can be extended with runtime messages. It is discarded when the runtime call ends. |
| Working Memory | Current run | No | Provides an explicit slot for temporary application/runtime state. It is discarded when the runtime call ends. |
| Long-term Memory | Across runs | Yes | Stores selected facts for one agent, subject to write, retrieval, expiration, and deletion policy. |

All three categories use `MemoryRecord`. Only records whose kind is `long_term` may cross the `MemoryStore` persistence boundary.

## Unified contracts

### `MemoryRecord`

- stable record ID;
- owning `agent_id`;
- `kind`: conversation, working, or long-term;
- bounded plain-text content;
- normalized importance in `[0, 1]`;
- optional source run;
- creation and expiration timestamps;
- small application-owned metadata dictionary.

### `MemoryStore`

The persistence port supports explicit `write`, agent-scoped `list`, agent-scoped `delete`, and `purge_expired`. The SQLAlchemy adapter stores only long-term records. Reads purge expired rows before returning data.

### `MemoryPolicy`

The policy decides whether a completed run proposes a write and deterministically ranks candidate records. It never writes by itself.

### `MemoryRetriever`

The retriever loads records through `MemoryStore` and applies `MemoryPolicy.rank`. Runtime adapters receive only the resulting `RuntimeMemory` snapshot, not a database session or store.

## Run flow

1. `AgentService` creates conversation memory for the current user message.
2. When memory is enabled, `MemoryRetriever` loads only non-expired records owned by that agent.
3. `MemoryPolicy` applies the relevance gate, scoring, result limit, and character budget.
4. A `memory.retrieved` trace event records record IDs and the relevance, recency, importance, and final scores. Memory contents are not duplicated into trace payloads.
5. The runtime receives conversation, working, and selected long-term memory in an application-owned snapshot.
6. The OpenAI adapter keeps selected facts in the serialized `AgentContext.memory` data field. Trusted agent instructions contain only the boundary rule that this field is untrusted user data; fact text is never concatenated into those instructions.
7. After successful runtime completion, the write policy may propose one long-term fact. The store commits it and `memory.written` records its ID, importance, expiration, and write reason.
8. Failed runs do not write long-term memory.

Writing happens before the terminal run event. Therefore a client that receives `run.completed` can immediately refresh the memory list and see committed data.

## Write policy

Long-term memory is not an automatic transcript archive. v1 accepts only:

1. explicit requests beginning with forms such as `Remember that ...` or `记住...`;
2. a small allowlist of stable fact shapes such as name, preferred language, timezone, favorite color, and project codename.

Explicit requests receive importance `0.9`; allowlisted stable facts receive `0.7`.

The policy rejects:

- empty or over-500-character facts;
- passwords, secrets, API keys, tokens, private keys, payment or government identifiers;
- prompt-like instructions such as requests to ignore, override, always, never, or follow system/developer messages;
- ordinary conversation and runtime output;
- writes from failed runs;
- every write while the agent's memory setting is disabled.

An identical active fact for the same agent is refreshed instead of duplicated. v1 does not use a model to infer or summarize memories, avoiding opaque writes and an API-key dependency in tests.

## Retrieval policy

Retrieval is always scoped by `agent_id` and excludes expired records. Query and memory text are normalized into lowercase ASCII words and Chinese bigrams. English stop words are removed.

Relevance is a token-overlap Dice coefficient:

```text
relevance = 2 * |query_terms ∩ memory_terms| / (|query_terms| + |memory_terms|)
```

A record must reach relevance `0.25` before ranking. This gate prevents a recent or important but unrelated fact from entering the prompt.

Passing records use:

```text
recency = 1 / (1 + age_days / 30)
score = 0.50 * relevance + 0.30 * importance + 0.20 * recency
```

The retriever returns at most five records and at most 1,500 content characters. Ties are deterministic: score, creation time, then record ID. These values are policy configuration, not hidden model behavior.

Known limitation: lexical retrieval does not understand synonyms or semantic equivalence. A future embedding implementation can replace the relevance component behind the same retriever/store boundaries, but it must retain the relevance gate, agent isolation, audit fields, and deterministic no-key test adapter.

## Expiration and deletion

- New long-term records expire after 180 days.
- Listing or retrieving memory physically purges records whose expiration time has passed.
- The API exposes physical deletion by both agent ID and memory ID. Supplying another agent's memory ID returns not found and cannot delete across agents.
- Deleted or expired memory is absent from later retrieval and therefore from prompts.
- Disabling memory does not silently delete existing records. It stops both retrieval and writes. Re-enabling resumes access to records that have not expired or been deleted.

## API and UI

Endpoints:

- `GET /agents/{agent_id}/memories` lists active long-term memory;
- `DELETE /agents/{agent_id}/memories/{memory_id}` deletes one owned record;
- `PATCH /agents/{agent_id}/memory-settings` enables or disables retrieval and writes.

The playground shows a `Remembered facts` section for the selected agent with importance, expiration, delete controls, and an on/off switch. UI state is refreshed after a terminal run so a newly committed fact becomes visible.

## Security and privacy

- Durable memory is treated as untrusted user data, not executable instructions.
- Prompt injection-like content is rejected at write time. Retrieved facts remain in the dedicated `context.memory` data field and are not promoted into trusted instructions.
- Trace events expose IDs and scores needed for debugging but do not replicate the fact text.
- Agent scope is applied in every list, delete, and retrieval query.
- v1 has no authentication or tenancy model; adding either requires tenant scope in every memory key and query before multi-user deployment.

## Tests

The backend suite verifies:

- a second run for the same agent retrieves a previously stored fact;
- unrelated memory does not enter runtime context;
- deleted memory is not retrieved;
- disabled memory does not write;
- agents are isolated;
- expired records are excluded;
- ordinary and sensitive inputs are not written;
- retrieval trace events expose all score components.

The frontend component test verifies that saved facts render and that delete and disable controls invoke their handlers.
