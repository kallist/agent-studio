# Development guide

## Current scope

This repository contains an engineering baseline, architecture decisions, a local database definition, and directory ownership notes. Frontend, backend, test, lint, typecheck, and E2E projects are **NOT IMPLEMENTED**. Do not run invented commands or claim those checks pass.

## Prerequisites

Planned development requires:

- Node.js and pnpm for `apps/web`;
- Python and a project-owned environment/package manager for `apps/api`;
- Docker with Docker Compose for PostgreSQL/pgvector;
- an optional `OPENAI_API_KEY` only for opt-in real-provider tests.

Use `.env.example` as a name-only template. Copy it to ignored `.env` and replace placeholders locally. Never commit the local file.

## Command contract

The following is the intended stable command surface. Commands marked planned must be implemented by the app scaffold that owns them; this baseline does not add dependencies merely to make placeholders appear runnable.

| Capability | Intended command | Current status |
|---|---|---|
| Database start | `docker compose up -d db` | Configured; container start NOT TESTED |
| Database status | `docker compose ps` | Configured; daemon interaction NOT TESTED |
| Database logs | `docker compose logs -f db` | Configured; daemon interaction NOT TESTED |
| Database stop | `docker compose down` | Configured; destructive volume removal is not included |
| Frontend dev | `pnpm --dir apps/web dev` | NOT IMPLEMENTED |
| Backend dev | project-owned Python runner from `apps/api` | NOT IMPLEMENTED |
| Backend tests | project-owned `pytest` command | NOT IMPLEMENTED |
| Frontend unit tests | project-owned Vitest command | NOT IMPLEMENTED |
| Lint | frontend and backend project commands | NOT IMPLEMENTED |
| Typecheck | TypeScript plus Python project commands | NOT IMPLEMENTED |
| E2E | project-owned Playwright command | NOT IMPLEMENTED |

When application manifests exist, add a small cross-platform root command layer only if it reduces real repetition. Do not add a monorepo orchestrator until multiple packages demonstrate a need for one.

## Planned project setup

### Frontend

Scaffold `apps/web` as a Next.js App Router project using TypeScript strict mode, Tailwind CSS, ESLint, Vitest, React Testing Library, and Playwright as project dependencies. Add shadcn/ui components selectively rather than installing a large component catalog.

### Backend

Scaffold `apps/api` as a Python project with FastAPI, Pydantic, SQLAlchemy, an async PostgreSQL driver, Alembic, pytest, formatting/linting, and static type checking. Keep the OpenAI Agents SDK dependency inside the runtime adapter package.

### Database

1. Create a local ignored `.env` from `.env.example`.
2. Set a local-only PostgreSQL password and matching `DATABASE_URL`.
3. Run `docker compose config` before starting services.
4. Run `docker compose up -d db`.
5. Wait for the `db` health check before running migrations or integration tests.

Do not commit database volumes, dumps containing sensitive data, or local credentials.

## Test strategy

- Unit tests exercise domain/application logic with deterministic fakes.
- Runtime contract tests compare normalized `AgentRuntime` outputs and events.
- Integration tests use PostgreSQL/pgvector and real repository adapters.
- Default tests use `MockProvider` and require no API key.
- Real OpenAI tests are opt-in, explicitly marked, and pass through the credential gate.
- Playwright E2E tests use the real web/API path and deterministic provider behavior.
- After UI work, use the in-app Browser for interaction, DOM, console, screenshot, and responsive validation.

## Quality gate

Before calling a feature complete, run every applicable command for build, lint, typecheck, unit, integration, E2E, and browser validation. State `NOT TESTED` for any absent or skipped check. Review the complete diff and scan staged files for secrets before committing.
