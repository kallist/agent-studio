# Agent Studio API

The FastAPI modular monolith: application services, domain contracts and ports, the bounded Agent
runtime, tool registry and executor, knowledge ingestion and retrieval, durable Memory, Evaluation,
observability, and SQLAlchemy persistence adapters.

Run it through the repository-level Docker Compose stack, or install it locally:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
.\.venv\Scripts\uvicorn.exe app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

Tests and static checks:

```powershell
.\.venv\Scripts\ruff.exe check apps/api scripts/ci
.\.venv\Scripts\mypy.exe apps/api/app
.\.venv\Scripts\pytest.exe apps/api/tests -m "not postgresql and not real_openai and not real_deepseek and not performance" -q
```

The default selection is offline and needs no provider key. PostgreSQL, real-provider, and performance
suites are opt-in via pytest markers.

See [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) for module boundaries,
[docs/RUN_LIFECYCLE.md](../../docs/RUN_LIFECYCLE.md) for the execution sequence, and
[docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md) for database configuration.
