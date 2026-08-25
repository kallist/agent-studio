# Real OpenAI integration and validation

This document is OpenAI-specific. See `MODEL_PROVIDERS.md` for the shared provider architecture and
the separately identified DeepSeek Chat Completions path.

Agent Studio keeps the outer `AgentLoop`, persistence, tool policy, RAG, Memory, Evaluation, and
product trace model application-owned. `AgentsSdkRuntime` is the only provider-facing SDK adapter.
Each application step starts a streamed Responses request with `max_turns=1`, consumes the stream
to terminal, and returns only an application `ProviderDecision` containing a final answer or one
captured function call plus bounded model/request/usage metadata.

SDK function callbacks never execute business tools. They parse one model `function_call` into an
application `ToolCall`; `ToolExecutor` then enforces the server registry, permissions, schemas,
input/output limits, timeout, duplicate-call policy, and audit events. Raw SDK stream events and
response objects do not cross the adapter.

## Configuration

- `OPENAI_API_KEY`: opt-in credential. Keep it only in the local environment or an uncommitted
  `.env`; never paste it into chat, tests, logs, or fixtures.
- Agent `model`, or `OPENAI_MODEL`: explicit Responses model ID. There is no time-sensitive
  hard-coded model default.
- `OPENAI_AGENTS_DISABLE_TRACING=1`: default. Sensitive trace inclusion is disabled even if SDK
  tracing is later enabled deliberately.
- `OPENAI_REQUEST_TIMEOUT_SECONDS=20`, `OPENAI_MAX_RETRIES=2`, and
  `OPENAI_MAX_OUTPUT_TOKENS=512`: bounded provider policy.
- `EMBEDDING_PROVIDER=openai` and `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`: opt in to online
  embeddings. The request always sends `dimensions=256`; vectors are never sliced.

`GET /providers/openai/readiness` reports only whether a non-blank key is configured, the optional
default model, and tracing state. It never performs a billable call and never returns the key.

## Test tiers

The default `pytest` suite is offline and does not call OpenAI. Online tests require all of:

1. `RUN_REAL_OPENAI_TESTS=1`
2. `OPENAI_API_KEY` set locally
3. explicit `OPENAI_REAL_TEST_MODEL`
4. for embeddings, explicit `OPENAI_REAL_EMBEDDING_MODEL`
5. for pgvector, the guarded loopback `POSTGRES_TEST_DATABASE_URL` and destructive-reset
   confirmation documented in `POSTGRESQL_PGVECTOR.md`

Run the bounded provider tests with:

```powershell
pytest -m real_openai tests/real_openai -q
pytest -m "real_openai and postgresql" tests/postgres/test_real_openai_pgvector.py -q
```

The tests use short prompts, at most three outer steps, one application invalid-output retry per
step, one calculator call, 128 output tokens per request, one SDK transport retry, and 30-second
provider timeouts. A missing key must be reported as:
`Real OpenAI: BLOCKED — OPENAI_API_KEY not configured`.

## Evidence and limitations

Usage is summed from completed provider calls into `requests`, `input_tokens`, `output_tokens`,
`total_tokens`, `cached_tokens`, and `reasoning_tokens` when supplied. Mock values remain `N/A`.
The configured model ID is persisted; the SDK does not expose a separate server-resolved model ID
in its normalized response object. Online tests are nondeterministic and billable, so they are not
evidence unless their current run output is attached to the delivery report.
