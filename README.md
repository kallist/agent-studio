# Agent Studio

Agent Studio is a development workbench for defining agents, running them through explicit runtime adapters, and inspecting application-owned tool and lifecycle events. It is not a ChatGPT clone.

The first runnable vertical slice now supports:

- persistent agent definitions with Mock/Demo, OpenAI, or DeepSeek runtime modes;
- a safe Calculator tool (`+`, `-`, `*`, `/`, unary signs, and parentheses);
- deterministic no-key runs through `MockRuntime`;
- one Agents SDK adapter behind the application-owned `AgentRuntime` port, resolving OpenAI
  Responses and DeepSeek OpenAI-compatible Chat Completions models;
- FastAPI endpoints plus same-origin SSE streaming;
- a responsive Next.js playground and ordered trace timeline;
- knowledge bases with secure txt/Markdown/PDF ingestion, asynchronous job states, chunking, embeddings, vector search, and inspectable citations;
- deterministic local RAG plus an opt-in OpenAI embedding provider and PostgreSQL/pgvector adapter;
- application-owned conversation, working, and policy-gated long-term memory;
- SQLite local persistence as the zero-infrastructure fallback;
- a verified PostgreSQL 17 + pgvector production-like development path.

See [ADR-001](docs/ADR/001-agent-runtime.md) for the accepted hybrid runtime boundary.
See [Memory System v1](docs/MEMORY_DESIGN.md) for write, retrieval, expiration, deletion, and isolation policy.

## Automated quality gates

Pull requests and main changes are configured for independent Backend, real PostgreSQL/pgvector,
Frontend, Playwright, Docker, Reliability, and Performance GitHub Actions checks. Default CI uses
only the deterministic Mock provider; real DeepSeek is a separate protected, manual workflow.
Main delivery validation builds and runs production images and emits delivery-ready evidence, but
does not deploy publicly or push a registry. See
[CI, reliability, performance, and delivery](docs/CI_RELIABILITY_PERFORMANCE.md).

## Docker quick start — recommended

Prerequisite: Docker Desktop, or Docker Engine with Docker Compose. No Python, Node.js, pnpm,
PostgreSQL, or LLM API key is required for the deterministic Mock demo.

```powershell
docker compose up --build -d
```

Open `http://127.0.0.1:3000`. The stack runs the Next.js production server, one production Uvicorn
process, and PostgreSQL 17 with pgvector. Web and API host ports bind only to loopback; PostgreSQL is
available only on the internal Docker network. The first start generates a project-scoped database
password in a Docker named volume rather than placing it in Compose source or container environment.

On Windows, the checked helper validates Docker, ports, provider configuration, Compose, and health:

```powershell
.\scripts\docker-up.ps1
.\scripts\docker-down.ps1
```

Normal `docker compose down` and `docker-down.ps1` preserve PostgreSQL, uploaded RAG sources, and
runtime-secret volumes. `docker-down.ps1 -PurgeData` is destructive and requires typing an explicit
project-name confirmation before it removes only this Compose project's volumes.

DeepSeek is opt-in. Supply `DEEPSEEK_API_KEY` to the host process and run:

```powershell
.\scripts\docker-up.ps1 -Provider deepseek
```

The helper streams the host value over stdin to a removed-after-use initializer, which stores only
the selected key in a project-scoped named volume mounted read-only only by API. It is not a build
argument, command-line value, source file, or persistent container environment value. OpenAI has the
equivalent `-Provider openai` configuration; real OpenAI container execution remains **NOT TESTED**.
See [Container runtime](docs/CONTAINER_RUNTIME.md) for provider helpers, secrets, persistence,
failure behavior, and known limitations.

This is a **containerized production-like local runtime**, not a production-ready internet service.
Authentication, RBAC, multi-tenancy, managed TLS/ingress, backups, horizontal scaling, distributed
workers, load certification, and cloud deployment are not implemented.

## Local development quick start

Prerequisites: Node.js 24+, pnpm 10+, and Python 3.12+.

```powershell
# Backend environment and dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"

# Frontend dependencies
pnpm --dir apps/web install

# Terminal 1: API
.\.venv\Scripts\uvicorn.exe app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000

# Terminal 2: web
pnpm --dir apps/web dev --hostname 127.0.0.1
```

Open `http://127.0.0.1:3000`.

The default database is the ignored `agent_studio.db` SQLite file. An explicit PostgreSQL URL is
never silently replaced with SQLite if the connection or pgvector initialization fails.

## PostgreSQL + pgvector host development

For host-process development against the disposable PostgreSQL test service, use the isolated
configuration documented in `docs/POSTGRESQL_PGVECTOR.md`. The default `compose.yaml` now owns the
complete production-like stack and intentionally does not publish PostgreSQL port 5432.

```powershell
$env:POSTGRES_TEST_PASSWORD = "local-integration-only"
docker compose -f compose.postgres-test.yaml up -d --wait
$env:DATABASE_URL = "postgresql+asyncpg://agent_studio_test:local-integration-only@127.0.0.1:55432/agent_studio_test"
.\.venv\Scripts\uvicorn.exe app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

Startup creates the application schema idempotently, enables the `vector` extension, creates the
fixed-dimension pgvector table and HNSW cosine index, and fails clearly when those operations cannot
complete. `GET /health` performs a live database readiness query while preserving the existing
`{"status":"ok"}` success contract. See
[PostgreSQL + pgvector](docs/POSTGRESQL_PGVECTOR.md) for architecture, test commands, and safety
limits.

## Mock demo

No API key is needed:

1. Create an agent named `Calculator Agent`.
2. Keep `Mock / Demo` selected and enable `calculator`.
3. Run `计算 128 * 37 + 456`.
4. Confirm the final answer is `5192` and the trace shows run start, runtime activity, tool selection, tool input, tool result, and final answer.
5. Refresh; the selected run and trace remain available through the URL.

OpenAI and DeepSeek are separate opt-in providers. Without the selected provider's server-side key,
the app still starts and returns `OpenAI provider is not configured.` or
`DeepSeek provider is not configured.` It never falls back to Mock or another real provider.

The real adapter uses `openai-agents==0.20.0` and `openai==2.54.0`, resolving OpenAI through the
Responses API and DeepSeek through OpenAI-compatible Chat Completions. It consumes each SDK stream
to a terminal event, translates aggregate request/token usage into
application events, and uses capture-only SDK function tools so the application `ToolExecutor`
still owns validation, permissions, timeouts, execution, and audit events. No model is silently
crossed between providers: an Agent model overrides its selected provider's configured default
(`OPENAI_MODEL` or `DEEPSEEK_MODEL`). See
[OpenAI integration](docs/OPENAI_INTEGRATION.md) for opt-in validation commands and limits.
See [Model providers](docs/MODEL_PROVIDERS.md) for provider identity, capability differences,
DeepSeek configuration, and explicit online validation gates.

## Quality commands

```powershell
.\.venv\Scripts\ruff.exe check apps/api
.\.venv\Scripts\mypy.exe apps/api/app
.\.venv\Scripts\pytest.exe apps/api/tests -q
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web test:run
pnpm --dir apps/web build
pnpm --dir apps/web e2e
```

Reliability and performance are explicit selections:

```powershell
.\.venv\Scripts\pytest.exe apps/api/tests -m "reliability and not postgresql" -q
$env:PERFORMANCE_OUTPUT = ".artifacts/performance-summary.json"
.\.venv\Scripts\pytest.exe apps/api/tests/postgres/test_performance_baseline.py -m performance -q -s
```

The PostgreSQL integration suite requires the disposable, loopback-only test service and explicit
test URLs documented in `docs/POSTGRESQL_PGVECTOR.md`. Its reset helper refuses non-loopback hosts,
databases or roles that do not end in `_test`, and runs only with the documented explicit destructive
reset confirmation.

## Repository map

```text
apps/api/       FastAPI, runtime ports/adapters, tools, persistence, tests
apps/web/       Next.js UI, unit tests, Playwright E2E
docs/           architecture, ADRs, run records, development guidance
infra/          local infrastructure notes
tests/          cross-application testing notes
```

## Knowledge and RAG

Create a knowledge base in the web UI, upload a supported document, wait for its ingestion state to become `completed`, and test retrieval directly. A new agent can attach one knowledge base and enable `knowledge_search`; source chunks and scores appear in the run trace.

The upload endpoint returns 202 after validation and durable job creation. The local worker handles parsing and embeddings in the background. See [RAG design](docs/RAG_DESIGN.md) for data models, chunking, retrieval, security, benchmark coverage, and production limitations.

## Evaluation

Create deterministic Evaluation Suites in the web UI to run real, isolated Agent executions and
grade final output, tool selection, RAG provenance, Memory retrieval, steps, and duration. Results
link back to the persisted Run Detail trace. See [Evaluation design](docs/EVALUATION_DESIGN.md) for
execution, aggregation, isolation, security, and v1 limitations.

## Roadmap (not implemented)

LLM-as-a-Judge, multi-agent orchestration, and distributed evaluation workers remain out of scope.

## Security

Agent Studio's default security model is a single-user local development workbench. The documented
commands bind to `127.0.0.1`; CORS/Host defaults are local and real providers are opt-in with no
silent provider fallback. RAG documents, Memory, user prompts, tool/provider output, and Evaluation values are
untrusted data. They do not gain system-instruction or tool-permission authority by entering a
runtime context.

Uploads are limited to validated UTF-8 txt/Markdown and text-extractable PDF files, stored under
generated application-owned names with byte, extraction, page, parser-time, and chunk bounds. Tool
execution, runtime steps, events, SSE queues, and Evaluation cardinality are also bounded. React
renders untrusted values as text; raw HTML/Markdown rendering is not implemented.

Never commit API keys, tokens, local `.env` files, local databases, or generated traces. The product
has **no authentication, RBAC, or multi-tenancy** and must not be exposed as a public/shared service.
See [Security Hardening v1](docs/SECURITY_DESIGN.md) for the threat model, trust boundaries,
implemented controls, tests, and known limitations.
