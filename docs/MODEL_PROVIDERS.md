# Model providers

Agent Studio has one application-owned runtime contract and one real-provider SDK adapter. It does
not duplicate the runtime for DeepSeek.

```text
AgentService -> AgentLoop -> AgentsSdkRuntime -> provider/model resolver
                                             |-> OpenAIResponsesModel
                                             `-> OpenAIChatCompletionsModel + DeepSeek AsyncOpenAI client
```

`AgentLoop`, run lifecycle, limits, cancellation, retries, tool permissions and execution, RAG,
Memory, Evaluation, normalized events, persistence, and security remain application-owned. SDK
types, raw responses, raw stream chunks, credentials, and provider-specific request settings do not
cross the runtime adapter.

## Provider identity and capabilities

| Provider | API style used here | Tool calls | Structured output | Reasoning config | Streaming | Usage | Responses-only fields |
|---|---|---:|---:|---:|---:|---:|---:|
| OpenAI | `responses` | yes | yes | provider-specific | yes | yes | yes |
| DeepSeek | `chat_completions` | yes | yes | provider-specific | yes | yes | no |

Each `llm.completed` event persists only normalized `provider`, requested `model`, `api_style`,
bounded request ID, stream-event count, and aggregate usage. Run observability projects the same
identity. API keys, base URL credentials, SDK objects, raw chunks, and raw provider responses are
never persisted or returned to the frontend.

DeepSeek now documents a Responses-compatible endpoint for some models, but this implementation
deliberately validates the broader official Chat Completions path selected for v1. It does not
send `previous_response_id`, `conversation_id`, hosted tools, `store`, `truncation`, or other
Responses-only settings to DeepSeek. DeepSeek thinking is explicitly disabled in its adapter for
this bounded v1 path instead of mechanically mapping OpenAI reasoning settings.

## Configuration

`LLM_PROVIDER=openai|deepseek` selects the preferred real provider reported by readiness. Agent
definitions retain an explicit `runtime_mode` so switching providers is visible and reproducible.
Both runtimes may be registered, but a run uses only its selected provider and never falls back.

OpenAI:

- `OPENAI_API_KEY`: server environment only.
- `OPENAI_API_KEY_FILE`: runtime secret-file alternative. Configuring both direct and file values
  fails closed; the Docker helper streams the host value into an API-only named volume over stdin.
- `OPENAI_MODEL`: optional default; an Agent model overrides it.
- `OPENAI_AGENTS_DISABLE_TRACING=1`: default.

DeepSeek:

- `DEEPSEEK_API_KEY`: server environment only.
- `DEEPSEEK_API_KEY_FILE`: runtime secret-file alternative. Configuring both direct and file values
  fails closed; the Docker helper streams the host value into an API-only named volume over stdin.
- `DEEPSEEK_MODEL=deepseek-v4-flash`: current default test/runtime model.
- `DEEPSEEK_BASE_URL=https://api.deepseek.com`: official origin. Validation rejects alternate,
  insecure, credential-bearing, query-bearing, and fragment-bearing URLs.
- `DEEPSEEK_REQUEST_TIMEOUT_SECONDS`, `DEEPSEEK_MAX_RETRIES`, and
  `DEEPSEEK_MAX_OUTPUT_TOKENS`: bounded transport policy.

The current official model IDs are `deepseek-v4-flash` and `deepseek-v4-pro`. Deprecated
`deepseek-chat` and `deepseek-reasoner` are not defaults. Model selection remains configuration-
driven.

`GET /providers/readiness` reports selected provider, separate configured yes/no state, default
model, API style, and capability flags for both providers. The provider-specific readiness routes
remain available. Readiness never performs a billable call or returns credentials.

## Embeddings are independent

`LLM_PROVIDER=deepseek` with `EMBEDDING_PROVIDER=local` is valid and is the tested DeepSeek RAG
shape. Embeddings remain an independent port with deterministic `local` and OpenAI implementations.
Agent Studio does not claim or require DeepSeek embeddings.

## Tool ownership and untrusted context

Agents SDK function callbacks are capture-only. A DeepSeek function call becomes an application
`ToolCall`; `ToolRegistry` and `ToolExecutor` then validate the name, schema, permissions, timeout,
output limit, duplicate-call policy, and actual execution. DeepSeek never receives callable Python
functions that bypass the executor. Memory and retrieved RAG content remain untrusted data inside
the serialized context.

## Test tiers

The default pytest and Playwright suites are offline and never call DeepSeek. Real DeepSeek tests
require `RUN_REAL_DEEPSEEK_TESTS=1` and a locally configured `DEEPSEEK_API_KEY`. The test model is
`DEEPSEEK_REAL_TEST_MODEL`, then `DEEPSEEK_MODEL`, then `deepseek-v4-flash`.

```powershell
pytest -m real_deepseek tests/real_deepseek -q
pytest -m "real_deepseek and postgresql" tests/postgres/test_real_deepseek_pgvector.py -q
pnpm --dir apps/web e2e -- real-deepseek.spec.ts
```

The online backend gate covers basic streamed Chat Completions, normalized usage, Calculator 5192,
application-owned RAG, Memory retrieval, and a real Evaluation case that references an evaluation
Run. The PostgreSQL gate uses deterministic local embeddings plus pgvector plus DeepSeek. The
explicit Playwright suite covers Basic Run, Calculator, RAG, and Memory. Online tests are billable
and nondeterministic; current results must be reported separately from OpenAI live gates.

## Container provider profiles

The default `compose.yaml` starts the deterministic Mock demo without mounting any provider key.
`docker-up.ps1 -Provider deepseek` streams the host value over stdin to a removed-after-use
initializer, then `compose.deepseek.yaml` mounts that project-scoped provider volume only into API
and requires provider configuration during startup. Missing key material fails clearly and cannot
fall back to Mock. `compose.openai.yaml` implements the equivalent `OPENAI_API_KEY_FILE` path.
DeepSeek's provider behavior has real online validation; a current container smoke must be reported
separately. Real OpenAI container validation remains **NOT TESTED**.

Official references used for this boundary:

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/create-chat-completion
- https://api-docs.deepseek.com/guides/tool_calls
- https://api-docs.deepseek.com/guides/thinking_mode/
