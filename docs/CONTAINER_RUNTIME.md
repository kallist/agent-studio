# Containerized production-like runtime

## 1. Goals

Run the complete Agent Studio stack from the repository root with Docker alone. The default path is
deterministic Mock Runtime plus PostgreSQL/pgvector and requires no LLM API key.

## 2. Scope

Task 12 containerizes the existing Next.js web app, FastAPI modular monolith, PostgreSQL 17/pgvector,
RAG files, local ingestion/evaluation workers, and application health lifecycle. It adds no Agent,
tool, RAG, Memory, Evaluation, or Observability product capability.

## 3. Production-like definition

The images use production servers, non-root app users, explicit startup ordering, health checks,
named persistence, runtime secrets, and local network segmentation. This is not an internet-ready
SaaS deployment: Auth, RBAC, multi-tenancy, public ingress/TLS, a cloud secret manager, managed DB,
automated backup/restore, Kubernetes, horizontal scaling, distributed workers, and production load
certification are not implemented.

## 4. Architecture

```text
Host browser -> 127.0.0.1:3000 -> Next.js standalone web
                                      -> http://api:8000
Host diagnostics -> 127.0.0.1:8000 -> FastAPI / Uvicorn (one process)
                                      -> PostgreSQL 17 + pgvector on db_network
```

Browser API and SSE calls remain same-origin `/api`; only the Next.js server resolves Docker DNS.

## 5. Container topology

`secret-init` idempotently creates DB credential files and assigns the RAG volume root to the fixed
non-root API UID without broad permissions; `db` starts and becomes healthy, `api`
performs current-schema and pgvector initialization and becomes healthy, then `web` starts. The
initializer is a one-shot infrastructure container with no network. Web never joins the DB network.

## 6. Web image

`apps/web/Dockerfile` uses Node 24, Corepack, pinned pnpm 10.18.2, and the frozen lockfile. Its
deps/builder/runtime stages copy only Next standalone output and static assets to the runtime image.
The runtime command is `node server.js`, with `NODE_ENV=production`; `next dev` is absent.

## 7. API image

`apps/api/Dockerfile` builds an application wheel plus pinned runtime dependencies with Python 3.12
slim, then installs only those wheels in the runtime stage. The runtime command is one Uvicorn
process listening on container address `0.0.0.0:8000`, with no reload and no multiprocess worker
claim.

## 8. PostgreSQL and pgvector

The database image is `pgvector/pgvector:pg17`. It is not published to the host. FastAPI selects
only `postgresql+asyncpg`, and an unavailable database or pgvector initializer prevents readiness;
there is no Docker-to-SQLite fallback.

## 9. Networks

Web and API share `app_network`. API and PostgreSQL share `db_network`, which is `internal: true`.
API retains outbound provider access through `app_network`; PostgreSQL has no public/app-only network.

## 10. Ports

Defaults are `127.0.0.1:3000:3000` and `127.0.0.1:8000:8000`. `WEB_PORT` and `API_PORT`, or the
Windows helper parameters, may change the host side explicitly. No random fallback port is chosen.

## 11. Secrets

The default stack generates a high-entropy PostgreSQL password and an encoded SQLAlchemy DSN in the
`runtime_secrets` named volume. PostgreSQL and API mount it read-only; Web has neither the mount nor
credential variables. For a provider profile, the helper streams the selected host key over stdin
to a removed-after-use, network-disabled initializer. The initializer writes an API-only
`provider_secrets` named volume; the key is never a build argument, command-line value, or persistent
container environment value. Direct values and `*_FILE` may not both be configured.

## 12. DeepSeek configuration

With `DEEPSEEK_API_KEY` present in the host process:

```powershell
.\scripts\docker-up.ps1 -Provider deepseek
```

The override sets `DEEPSEEK_API_KEY_FILE` and requires the selected provider to be configured. Use
the helper for provider profiles because it owns the stdin-to-named-volume initialization step;
running the override alone without an initialized volume fails closed. Missing key material fails
clearly and never falls back to Mock.

## 13. OpenAI limitation

`compose.openai.yaml` and `docker-up.ps1 -Provider openai` implement the same runtime-secret path.
Real OpenAI Responses/embeddings inside the container are **NOT TESTED**.

## 14. Database configuration

Non-Docker development keeps `DATABASE_URL`. Docker uses `DATABASE_URL_FILE` generated from the
safe Compose DB host/name/user and runtime password. The resolved URL is never logged. Supported
backends remain exactly `sqlite+aiosqlite` and `postgresql+asyncpg`.

## 15. Persistent volumes

- `postgres_data`: system of record for agents, runs/events, Memory, RAG metadata/vectors, and Eval.
- `knowledge_data`: original uploaded sources required by ingestion restart recovery.
- `runtime_secrets`: the DB credential coupled to the persistent DB volume.
- `provider_secrets`: the selected opt-in provider key, mounted only by its initializer and API.

Normal restart, rebuild, and `down` preserve all four.

## 16. Schema initialization

FastAPI lifespan remains the single initialization path: SQLAlchemy `create_all`, bounded legacy
compatibility migrations, then idempotent pgvector extension/table/index validation. Fresh databases
and repeated current-schema startup are supported. A versioned historical migration framework such
as Alembic is **NOT IMPLEMENTED**.

## 17. Startup order

Compose conditions enforce secret initializer completion -> PostgreSQL health -> API health -> Web
health. API health is not marked ready until schema/vector initialization and worker startup finish.

## 18. Health and readiness

PostgreSQL uses `pg_isready`. API `/health` executes a live `SELECT 1` and returns a safe 503 on DB
loss. Web checks `/` with Node's built-in HTTP client. No curl package is added.

## 19. Graceful shutdown

App services use Docker init and finite grace periods. Compose sends normal stop signals; Uvicorn
lifespan stops evaluation and ingestion workers before disposing provider/database resources.
PostgreSQL receives its normal shutdown path.

## 20. Background worker behavior

The existing application-local workers remain concurrency one. Startup requeues abandoned
ingestion processing jobs and queued/running EvaluationRuns using persisted state. Distributed
workers and horizontal API process scaling are **NOT IMPLEMENTED / NOT TESTED**.

## 21. Recovery

API or whole-stack restart uses persisted job state and RAG source files. DB restart temporarily
makes API readiness fail; recovery uses the same PostgreSQL URL and never creates SQLite state.

## 22. Logs

Services log to stdout/stderr at INFO. Compose uses the local logging driver with bounded rotation.
Provider SDK verbose debugging remains off; credentials, provider payloads, Memory, and RAG bodies
must not be logged.

## 23. Security

App containers drop all Linux capabilities, deny privilege escalation, use read-only root filesystems
and bounded `/tmp` tmpfs, mount only required volumes, and have no privileged mode, host networking,
source bind mount, or Docker socket. Existing Task 09 application controls remain authoritative.

## 24. Non-root containers

API and Web run as stable UID/GID `10001:10001`. The one-shot secret initializer runs as root only
to initialize a new Docker volume, has no network, and exits; the long-lived API/Web processes are
never root.

## 25. Image hygiene

The root `.dockerignore` excludes Git metadata, `.env*` except `.env.example`, local secret paths,
virtualenvs, node_modules, builds, caches, tests artifacts, local DBs, dumps, and traces. Provider
credentials are not Dockerfile arguments or environment values. Runtime images exclude backend tests,
Playwright, the pnpm store, and frontend dev dependencies.

## 26. One-command startup

Cross-platform:

```text
docker compose up --build -d
```

Windows with daemon/port/config/health checks:

```powershell
.\scripts\docker-up.ps1
```

Repeating either command reconciles the same stable Compose project and volumes.

## 27. Data reset

`docker compose down` or `docker-down.ps1` preserves data. The only provided purge UX is
`docker-down.ps1 -PurgeData`, which warns and requires the exact `PURGE <project>` confirmation.
It targets only the named Compose project; system/volume prune is never used.

## 28. Test strategy

Configuration/secret unit tests and static Docker safety tests complement real gates: Compose config,
clean image builds, cold/warm start, live pgvector catalog inspection, non-root/network/secret checks,
container-targeted Playwright, persistence/restart, failure behavior, dependency audits, and diff/
secret hygiene. Static inspection alone is not acceptance evidence.

## 29. Failure behavior

Docker daemon offline, occupied ports, invalid provider, missing selected provider key, missing/empty
secret file, invalid DB identifier/port, DB authentication failure, PostgreSQL loss, and pgvector
initialization failure all fail explicitly. Error messages name configuration categories but never
echo secret values or password-bearing URLs.

## 30. Known limitations

No Auth/RBAC/multi-tenancy, managed TLS/public ingress, cloud secret manager, formal migration
baseline, backup/restore automation, distributed queue/worker, horizontal API scaling, Kubernetes,
cloud deployment, production load certification, or resource tuning. Host reboot is represented by
stop/start persistence testing, not a physical Windows reboot.

## 31. Future deployment work

Task 13 may address CI/CD, reliability, performance, failure testing, release automation, image
scanning/signing, backup verification, and measured resource policy. Internet-service architecture
requires separate Auth/tenancy/ingress/managed-infrastructure decisions.
