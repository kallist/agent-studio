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
| Production-like Docker stack | `.\scripts\docker-up.ps1` |
| Docker E2E | `pnpm --dir apps/web e2e:docker` |
| Reliability selection | `.\.venv\Scripts\pytest.exe apps/api/tests -m "reliability and not postgresql" -q` |
| Performance baseline | `.\.venv\Scripts\pytest.exe apps/api/tests/postgres/test_performance_baseline.py -m performance -q -s` |
| Repository/workflow safety | `.\.venv\Scripts\python.exe scripts/ci/validate_repository.py` |

## Persistence

Host-native development defaults to the ignored
`sqlite+aiosqlite:///./agent_studio.db` file. Repository and application contracts contain no
SQLite-specific behavior.

The recommended production-like local runtime is the complete Docker stack in `compose.yaml`. It
starts PostgreSQL 17 plus pgvector, the FastAPI API, and the standalone Next.js server, generates a
project-scoped database credential in a named volume, and waits for health dependencies:

```powershell
.\scripts\docker-up.ps1
```

See `docs/CONTAINER_RUNTIME.md` for lifecycle, provider-secret, backup, recovery, port, and explicit
production-readiness boundaries. The Docker runtime fails closed when PostgreSQL is unavailable and
never falls back to SQLite.

## OpenAI mode

Mock mode is the default demo and test path. For host-native opt-in OpenAI or DeepSeek runs, set the
provider key only in the process environment or an ignored local `.env`. In the Docker runtime, use
`docker-up.ps1 -Provider openai` or `-Provider deepseek`; the helper streams the selected key to an
API-only named volume and mounts it as a secret file. Never place a value in `.env.example` or source
control. Provider integrations remain
isolated behind the application runtime/provider boundaries.

## Testing notes

Playwright owns its Chromium browser dependency. Install it once with:

```powershell
pnpm --dir apps/web exec playwright install chromium
```

The default E2E configuration starts host-native web and API servers and uses the deterministic Mock
runtime. `e2e:docker` instead targets the running production-like Compose stack. Real OpenAI and
DeepSeek execution are explicit opt-in suites and are not part of default tests.

## CI and delivery reproduction

Use the guarded PostgreSQL variables from `POSTGRESQL_PGVECTOR.md` for functional and performance
database selections. Set `PERFORMANCE_OUTPUT=.artifacts/performance-summary.json` for a
machine-readable result; this never changes `docs/performance-baseline.json`.

The production-like restart/recovery path is locally reusable:

```powershell
.\.venv\Scripts\python.exe scripts/ci/docker_reliability.py `
  --project-name agent-studio-v1-local `
  --artifact .artifacts/delivery-metadata.json
```

The project-name prefix is mandatory so the runner can operate only its own Compose resources. See
`docs/CI_RELIABILITY_PERFORMANCE.md` for the CI matrix, timeouts, artifact policy, and main delivery
meaning.
