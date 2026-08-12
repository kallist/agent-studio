# Development guide

## Implemented command surface

| Capability | Command |
|---|---|
| Backend dev | `.\.venv\Scripts\uvicorn.exe app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000` |
| Backend lint | `.\.venv\Scripts\ruff.exe check apps/api` |
| Backend typecheck | `.\.venv\Scripts\mypy.exe apps/api/app` |
| Backend tests | `.\.venv\Scripts\pytest.exe apps/api/tests -q` |
| Frontend dev | `pnpm --dir apps/web dev --hostname 127.0.0.1` |
| Frontend lint | `pnpm --dir apps/web lint` |
| Frontend typecheck | `pnpm --dir apps/web typecheck` |
| Frontend unit tests | `pnpm --dir apps/web test:run` |
| Frontend build | `pnpm --dir apps/web build` |
| E2E | `pnpm --dir apps/web e2e` |

## Persistence

The application defaults to `sqlite+aiosqlite:///./agent_studio.db`. This is a temporary local fallback selected because Docker Desktop's daemon was not running during the vertical-slice build. Repository and application contracts contain no SQLite-specific behavior, and local database files are ignored.

PostgreSQL/pgvector remains preferred. Once Docker Desktop is available:

1. Set a local-only `POSTGRES_PASSWORD` and async `DATABASE_URL` in ignored environment configuration.
2. Run `docker compose config`.
3. Run `docker compose up -d db` and wait for health.
4. Start the API with that `DATABASE_URL`.

## OpenAI mode

Mock mode is the default demo and test path. For opt-in OpenAI runs, set `OPENAI_API_KEY` only in the process environment or an ignored local `.env`. Never place a value in `.env.example` or source control. The SDK integration is isolated in `apps/api/app/runtime/agents_sdk.py`.

## Testing notes

Playwright owns its Chromium browser dependency. Install it once with:

```powershell
pnpm --dir apps/web exec playwright install chromium
```

The E2E configuration starts both web and API servers and uses the deterministic Mock runtime. Real OpenAI execution is not part of default tests.
