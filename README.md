# Agent Studio

Agent Studio is a development workbench for defining agents, running them through explicit runtime adapters, and inspecting application-owned tool and lifecycle events. It is not a ChatGPT clone.

The first runnable vertical slice now supports:

- persistent agent definitions with Mock/Demo or opt-in OpenAI runtime mode;
- a safe Calculator tool (`+`, `-`, `*`, `/`, unary signs, and parentheses);
- deterministic no-key runs through `MockRuntime`;
- an OpenAI Agents SDK adapter behind the application-owned `AgentRuntime` port;
- FastAPI endpoints plus same-origin SSE streaming;
- a responsive Next.js playground and ordered trace timeline;
- knowledge bases with secure txt/Markdown/PDF ingestion, asynchronous job states, chunking, embeddings, vector search, and inspectable citations;
- deterministic local RAG plus an opt-in OpenAI embedding provider and PostgreSQL/pgvector adapter;
- SQLite local persistence as a documented fallback while Docker Desktop is unavailable.

See [ADR-001](docs/ADR/001-agent-runtime.md) for the accepted hybrid runtime boundary.

## Quick start

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

The default database is the ignored `agent_studio.db` SQLite file. PostgreSQL/pgvector remains the preferred development database and can be selected by setting `DATABASE_URL` after Docker Desktop is running.

## Mock demo

No API key is needed:

1. Create an agent named `Calculator Agent`.
2. Keep `Mock / Demo` selected and enable `calculator`.
3. Run `计算 128 * 37 + 456`.
4. Confirm the final answer is `5192` and the trace shows run start, runtime activity, tool selection, tool input, tool result, and final answer.
5. Refresh; the selected run and trace remain available through the URL.

OpenAI mode is opt-in. Without `OPENAI_API_KEY`, the app still starts and returns the explicit error `OpenAI provider is not configured.` It never falls back silently to Mock mode.

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

## Roadmap (not implemented)

Durable memory policy, full evaluation workflows, and multi-agent orchestration remain out of scope for this vertical slice.

## Security

Never commit API keys, tokens, local `.env` files, or local databases. `.env.example` contains names and non-secret defaults only.
