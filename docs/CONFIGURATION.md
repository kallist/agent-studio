# Configuration reference

Agent Studio reads uppercase environment variables through FastAPI settings. `.env.example` contains names and placeholders only; never commit a populated `.env`.

## Runtime and persistence

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` or `production-like` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./agent_studio.db` | Explicit SQLite or `postgresql+asyncpg` URL |
| `DATABASE_URL_FILE` | unset | Runtime-secret file alternative; mutually exclusive with an explicit URL |
| `LLM_PROVIDER` | `openai` | Preferred real provider reported by readiness: `openai` or `deepseek` |
| `REQUIRE_LLM_PROVIDER_CONFIGURED` | `0` | Fail startup when the selected real provider lacks a key |
| `CORS_ORIGINS` | local Web origins | Explicit comma-separated browser origins; wildcard rejected |
| `ALLOWED_HOSTS` | local/test hosts | Explicit comma-separated hosts; wildcard rejected |

An Agent definition selects its own `runtime_mode` (`mock`, `openai`, or `deepseek`). `LLM_PROVIDER` does not silently rewrite existing Agents and no provider falls back to another.

## Providers

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` / `OPENAI_API_KEY_FILE` | unset | Direct host secret or file secret, never both |
| `OPENAI_MODEL` | unset | Optional default Responses model; Agent model wins |
| `OPENAI_AGENTS_DISABLE_TRACING` | `1` | Disables SDK trace export by default |
| `OPENAI_REQUEST_TIMEOUT_SECONDS` | `20` | Request timeout, 0–120 seconds |
| `OPENAI_MAX_RETRIES` | `2` | Transport retries, 0–5 |
| `OPENAI_MAX_OUTPUT_TOKENS` | `512` | Output bound, 64–4096 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEY_FILE` | unset | Direct host secret or file secret, never both |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | Default DeepSeek model |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Validated official HTTPS origin only |
| `DEEPSEEK_REQUEST_TIMEOUT_SECONDS` | `20` | Request timeout, 0–120 seconds |
| `DEEPSEEK_MAX_RETRIES` | `2` | Transport retries, 0–5 |
| `DEEPSEEK_MAX_OUTPUT_TOKENS` | `512` | Output bound, 64–4096 |

Use `.\scripts\docker-up.ps1 -Provider deepseek|openai` for Docker provider secrets. The default Compose profile uses Mock Agents and mounts no provider key.

## Knowledge and Evaluation

| Variable | Default | Purpose |
|---|---|---|
| `EMBEDDING_PROVIDER` | `local` | `local` or `openai` |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model when opted in |
| `KNOWLEDGE_STORAGE_PATH` | `./data/knowledge` | Application-owned source storage |
| `KNOWLEDGE_MAX_FILE_BYTES` | `10485760` | Upload byte bound, at most 50 MiB |
| `KNOWLEDGE_MAX_EXTRACTED_CHARS` | `2000000` | Extracted text bound |
| `KNOWLEDGE_MAX_CHUNKS` | `5000` | Per-document chunk bound |
| `KNOWLEDGE_PARSER_TIMEOUT_SECONDS` | `15` | Parser timeout |
| `KNOWLEDGE_WORKER_COUNT` | `1` | In-process ingestion workers, 1–8 |
| `EVALUATION_WORKER_COUNT` | `1` | In-process evaluation workers, 1–8 |

## Docker helper options

`.\scripts\docker-up.ps1` accepts `-Provider mock|deepseek|openai`, `-WebPort`, `-ApiPort`, and `-ProjectName`. The default ports are 3000 and 8000. `WEB_PORT`, `API_PORT`, `POSTGRES_DB`, and `POSTGRES_USER` are Compose substitutions; PostgreSQL's generated password is not a source variable.

Test-only variables such as `POSTGRES_TEST_DATABASE_URL`, `POSTGRES_TEST_ALLOW_DESTRUCTIVE_RESET`, `RUN_REAL_DEEPSEEK_TESTS`, and `RUN_REAL_OPENAI_TESTS` are documented with their guarded suites in [PostgreSQL + pgvector](POSTGRESQL_PGVECTOR.md) and [Model providers](MODEL_PROVIDERS.md). They are not normal runtime configuration.
