# Engineering baseline

> Historical repository-start snapshot. It does not describe the current v1 product; see [V1_STATUS.md](V1_STATUS.md) for current implementation and validation claims.

Recorded: 2026-08-13 (Asia/Shanghai)

This document records verified facts, not planned behavior. Planned architecture and commands live in `ARCHITECTURE.md` and `DEVELOPMENT.md`.

## Repository status

- Git repository initialized on `main`.
- This engineering baseline is intended to be the first commit.
- No remote repository is configured by this baseline.
- No push, release, or pull request is part of this work.
- Project instructions are now defined in `AGENTS.md`.

## Business code status

- Agent Studio MVP is **NOT IMPLEMENTED**.
- There is no frontend application, FastAPI application, agent runtime implementation, tool implementation, persistence model, migration, RAG pipeline, trace UI, or evaluation engine.
- `apps/web` and `apps/api` are ownership placeholders only.

## Available tooling

The detailed live-session inventory is `CODEX_CAPABILITIES.md`. Relevant verified capabilities include Git, GitHub CLI and connector access, Node/npm/pnpm, bundled Python, Docker CLI, the in-app Browser, Computer Use enumeration, OpenAI Docs access, document artifact runtimes, and the local Skill/plugin inventory.

Docker CLI presence does not prove that the Docker daemon can start containers. The daemon remains **NOT TESTED** in this baseline.

## Configuration status

- `.gitignore` excludes real environment files, common secrets, build/test caches, dependencies, and local databases while allowing `.env.example`.
- `.env.example` contains placeholders only.
- `compose.yaml` defines one PostgreSQL/pgvector development service with a named volume and health check.
- Docker Compose v5.1.4 parsed `compose.yaml` successfully with a temporary placeholder password; no image pull or container start occurred.
- No real credential, API key, connection string, database dump, or local `.env` is committed.

## Test status

| Check | Status |
|---|---|
| Application build | NOT TESTED — no application exists |
| Lint | NOT TESTED — no project lint configuration exists |
| Typecheck | NOT TESTED — no project typecheck configuration exists |
| Unit tests | NOT TESTED — no project unit test configuration exists |
| Integration tests | NOT TESTED — no application or database test harness exists |
| E2E tests | NOT TESTED — no application or Playwright project exists |
| Browser validation | NOT TESTED — no UI exists |
| Docker container startup | NOT TESTED — daemon/container execution was not required |

Documentation consistency, Compose parsing, Git whitespace checks, and secret-pattern scanning are baseline validation checks rather than application tests. Their final results are recorded in the baseline commit handoff.

## Database status

- PostgreSQL/pgvector is selected for development and represented by Compose configuration.
- No container, database, schema, table, extension migration, or seed data has been created.
- No PostgreSQL client was found during the capability audit.
- Bundled Python `sqlite3` works, but SQLite has not been selected or used by this project.

## Agent runtime status

- ADR-001 selects a hybrid runtime: OpenAI Agents SDK inside an application-owned `AgentRuntime` adapter.
- The decision is based on current official OpenAI documentation reviewed during this baseline.
- No Agents SDK package is installed in the repository and no API call was made.
- `OpenAIProvider`, `MockProvider`, and all runtime/store interfaces are designs only.

## Known limitations and open implementation work

- Application dependencies and lockfiles do not exist.
- Unified frontend/backend/test commands are planned but not implemented.
- Docker daemon availability and the selected pgvector image pull are not verified.
- Authentication, tenancy, background jobs, object storage, production deployment, and the evaluation schema are intentionally deferred.
- Canva remains unavailable until reauthenticated; no project work depends on it.
