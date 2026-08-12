# Vertical slice run 02

## Goal

Implement the first end-to-end Agent Studio path: create a persistent Mock calculator agent, submit `计算 128 * 37 + 456`, execute the safe Calculator through `ToolExecutor`, stream normalized events, show `5192`, and preserve the run after refresh.

## Skills used

- `openai-docs`: verified current official Agents SDK concepts before adding the dependency.
- `agents-sdk`: followed the Python single-agent, `Runner.run`, `@function_tool`, and adapter guidance.
- `control-in-app-browser`: performed real localhost interaction, console inspection, responsive checks, and persistence validation.
- `review-agent`: used after implementation for a read-only defect-first diff review.

## Plugins and MCP

- OpenAI Developers plugin Skill supplied the Agents SDK implementation workflow. No OpenAI API call was made.
- Browser plugin with the `node_repl` MCP controlled the Codex in-app Browser.
- No GitHub, Canva, Computer Use, database SaaS, or external connector was needed.

## Official documentation checked

Checked on 2026-08-13 before implementation:

- https://developers.openai.com/api/docs/guides/agents
- https://developers.openai.com/api/docs/guides/agents/quickstart
- https://developers.openai.com/api/docs/guides/agents/define-agents
- https://developers.openai.com/api/docs/guides/agents/models
- https://developers.openai.com/api/docs/guides/agents/running-agents
- https://developers.openai.com/api/docs/guides/agents/results
- https://developers.openai.com/api/docs/guides/agents/integrations-observability
- https://developers.openai.com/api/docs/guides/tools
- https://developers.openai.com/api/docs/guides/agent-evals

Confirmed current Python installation and usage:

- package: `openai-agents==0.20.0`;
- agent definition: `Agent(name, instructions, model, tools, output_type)`;
- function tools: `@function_tool` with typed Python parameters;
- execution: `await Runner.run(...)` and `Runner.run_streamed(...)` for SDK streaming;
- result: application reads only `final_output` at the adapter boundary;
- structured output: Pydantic model passed as `output_type` when required;
- model configuration: agent `model` plus SDK model settings when needed;
- tracing: SDK tracing is enabled by default on the normal server path, but Agent Studio persists its own normalized product events;
- errors: provider and tool errors are translated into application errors/events;
- testing: default tests use `MockRuntime`; real provider execution remains opt-in.

## Architecture decisions

- ADR-001 remains accepted and unchanged: SDK imports appear only in `runtime/agents_sdk.py` and its contract-focused tests.
- `AgentRuntime` accepts application `RuntimeInput`, an async event sink, and returns `RuntimeOutput`.
- `AgentDefinition`, `RunRequest`, `RunResult`, `RunStatus`, and `AgentEvent` are application-owned Pydantic contracts.
- Run events have stable IDs, run IDs, monotonic sequence numbers, timestamps, types, and type-specific payloads. They expose tool decisions, arguments, outputs, latency, concise summaries, errors, and final output—never private chain-of-thought.
- `ToolRegistry` owns definitions; `ToolExecutor` validates arguments, enforces timeouts and output limits, and invokes adapters.
- Calculator uses a strict AST allowlist. Calls, attributes, imports, variables, collections, exponentiation, and arbitrary code are rejected.
- SSE first replays persisted events, then subscribes to an in-memory queue for live events. The client uses a same-origin Next.js `/api` proxy.
- Docker daemon was unavailable (`docker info` could not connect), so SQLAlchemy repositories use the documented SQLite fallback. PostgreSQL/pgvector remains preferred.

## Files changed

- Backend project, domain contracts, runtime adapters, tools, SQLAlchemy persistence, FastAPI routes, SSE, and 19 pytest tests under `apps/api`.
- Next.js application, responsive UI, typed API client, trace timeline, Vitest test, and Playwright E2E under `apps/web`.
- Root environment example, README, development guide, and this run record.

## Commands run

- `docker info --format '{{json .ServerVersion}}'` — FAIL: Docker Desktop daemon not running.
- project Python dependency install with pip into `.venv` — PASS.
- `pnpm --dir apps/web install` — PASS.
- `pnpm --dir apps/web exec playwright install chromium` — PASS.
- All final quality commands are listed in the Tests section.

## Tests

Final validation after review fixes:

- Backend Ruff: PASS (`All checks passed!`).
- Backend mypy: PASS (`Success: no issues found in 20 source files`).
- Backend pytest: PASS (`22 passed`).
- Frontend ESLint: PASS.
- Frontend TypeScript: PASS.
- Frontend Vitest: PASS (`2 passed`).
- Next.js production build: PASS.
- Playwright E2E: PASS (`1 passed`), rerun after ordering API before Web startup to remove the proxy startup race.

## Browser validation

Using the Codex in-app Browser against live Next.js and FastAPI services:

1. Opened `http://127.0.0.1:3000`.
2. Confirmed Agent Studio loaded and initial console had no errors/warnings.
3. Confirmed agent list empty state on the first clean browser run.
4. Opened Create Agent.
5. Entered `Calculator Agent`.
6. Entered calculator instructions.
7. Selected visible `Mock / Demo · no API key` runtime.
8. Confirmed `calculator` tool enabled.
9. Saved and confirmed it appeared in the list.
10. Entered `计算 128 * 37 + 456`.
11. Ran the agent.
12. Confirmed final output `5192`.
13. Confirmed ordered events: run start, runtime start, tool selected, tool input, tool result `5192` with latency, runtime complete, final answer.
14. Refreshed and confirmed the Agent, completed Run, and all 7 events persisted.
15. Confirmed browser console and final backend logs contained no errors/warnings.
16. Checked 390×844 responsive layout, then reset the viewport and checked desktop layout.

## Bugs found and fixed

- Next.js 16 blocked `127.0.0.1` dev resources: added `allowedDevOrigins`.
- Vitest discovered Playwright files and could not resolve `@`: excluded `e2e` and added the alias.
- Playwright Chromium was absent: installed the project-owned browser binary.
- Runtime emitted terminal event before terminal status persistence, causing the SSE stream to end ambiguously: application service now persists terminal status before publishing its terminal event.
- EventSource normal close could show a false disconnect error: client now restores terminal state and trace from persistence.
- Direct cross-origin API recovery was unreliable in the in-app Browser: switched to a same-origin Next.js `/api` proxy.
- SSE disconnect could cancel a live SQLite query and log connection cleanup errors: replaced repeat-query live waiting with a persisted replay plus in-memory subscriber queue.
- Review found that the configured OpenAI key was only used as a boolean gate: the adapter now builds an explicit `AsyncOpenAI` client with that key and passes an SDK model plus trace configuration.
- Review found terminal run status and terminal event used separate transactions: they now commit atomically before publishing to SSE subscribers.
- Review found Mock runtime ignored an agent with calculator disabled: it now fails clearly and has an API regression test.
- Review found PostgreSQL configuration lacked `asyncpg`: added the pinned project dependency.
- Review found Python booleans passed the numeric AST check: calculator now rejects them and has a regression case.

## Remaining limitations

- Docker Desktop was not running, so PostgreSQL/pgvector container integration is NOT TESTED in this run.
- A real OpenAI call is NOT TESTED because no credential was requested or used. Credential gating, adapter initialization, SDK import isolation, and application contracts are tested.
- Authentication, RAG/knowledge, durable memory, evals, multi-agent orchestration, MCP marketplace, billing, deployment, dashboards, and workflow builders remain out of scope.
