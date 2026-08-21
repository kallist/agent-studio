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
7. After successful runtime completion, the write policy may propose one long-term fact. Finalization first acquires the same database-owned agent synchronization point used by memory settings updates, then rereads the current persisted setting. A single transaction conditionally upserts the fact only when that setting is enabled, appends `memory.written`, and persists `run.completed` plus the terminal run state.
8. If any part of that completion transaction fails, the memory write, memory event, and terminal transition roll back together. Failed runs do not write long-term memory.

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

Content is normalized with Unicode NFKC, case folding, and whitespace collapsing, then hashed with SHA-256. `(agent_id, normalized_key)` is database-unique, and writes use an atomic upsert, so concurrent runs cannot create duplicate facts for one agent. A repeated fact refreshes its timestamps and source while retaining the greatest importance. Each successful run-level upsert emits `memory.written`, including an upsert that deduplicates an existing fact; both events identify the same canonical record. v1 does not use a model to infer or summarize memories, avoiding opaque writes and an API-key dependency in tests.

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

The retriever returns at most five records and at most 1,500 content characters. Every record, including the first ranked record, must fit the remaining budget; oversized records are deterministically skipped rather than truncated. Ties are deterministic: score, creation time, then record ID. These values are policy configuration, not hidden model behavior.

Known limitation: lexical retrieval does not understand synonyms or semantic equivalence. A future embedding implementation can replace the relevance component behind the same retriever/store boundaries, but it must retain the relevance gate, agent isolation, audit fields, and deterministic no-key test adapter.

## Expiration and deletion

- New long-term records expire after 180 days.
- Listing or retrieving memory physically purges records whose expiration time has passed.
- The API exposes physical deletion by both agent ID and memory ID. Supplying another agent's memory ID returns not found and cannot delete across agents.
- Deleted or expired memory is absent from later retrieval and therefore from prompts.
- Disabling memory does not silently delete existing records. It stops both retrieval and writes. Re-enabling resumes access to records that have not expired or been deleted.

### Disable/finalization ordering

Memory settings changes and run finalization are linearizable database operations:

- PostgreSQL locks the corresponding `agents` row with `SELECT ... FOR UPDATE` before either operation reads or changes memory settings. The lock is held through the settings commit or through the atomic Memory/event/terminal commit.
- SQLite does not claim row-lock support. Both operations start with `BEGIN IMMEDIATE`, so SQLite's write reservation serializes them before either reads the enabled flag. This is deliberately database-wide and coarser than PostgreSQL, but deterministic for the supported local/test adapter.
- If disable owns and commits the synchronization point first, finalization subsequently sees `enabled=false`, completes the run without durable Memory, and does not emit `memory.written`.
- If finalization owns the synchronization point first, it may atomically commit its already-authorized Memory, `memory.written`, and terminal state. Disable waits, then commits `enabled=false`; runs finalized after that commit cannot write Memory.

This ordering does not retroactively cancel a finalization transaction that already owns the synchronization point. It guarantees that a completed disable cannot be followed by a durable write from an older finalization transaction that had not already acquired ownership.

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
- deterministic interleavings cover both disable-wins and finalization-wins ordering;
- terminal persistence failure rolls back the memory write;
- concurrent equivalent writes deduplicate through the database constraint;
- two concurrent application runs traverse runtime finalization, event persistence, terminal state, and the atomic upsert while producing one canonical Memory;
- fixed-clock ranking covers relevance, importance, recency, threshold, ties, result limit, and context budget;
- a combined RAG/Memory run preserves retrieval, `knowledge_search`, citations, memory write, and normalized event order.

The PostgreSQL integration suite uses independent real connections at `READ COMMITTED` and
deterministically validates both row-lock orderings, complete concurrent Run deduplication, and
atomic rollback after terminal-event failure. The `SELECT ... FOR UPDATE` behavior is no longer a
SQL-compilation-only claim. SQLite continues to run the complete default backend suite.

The frontend component test verifies that saved facts render and that delete and disable controls invoke their handlers.
