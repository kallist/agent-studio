# PostgreSQL + pgvector integration

## Goals

This integration makes PostgreSQL the verified production-like persistence adapter while retaining
SQLite as the default zero-infrastructure local fallback. It validates real PostgreSQL transaction
semantics and real pgvector storage/search without changing the application, runtime, RAG, Memory,
Observability, or Evaluation boundaries.

## Architecture

Application services continue to depend on `Repositories`, `KnowledgeRepository`, `MemoryStore`,
and `VectorStore`. `DATABASE_URL` selects the SQLAlchemy backend once during application wiring.
Business workflows do not branch on a database dialect. Dialect-specific row ownership, upsert, and
vector SQL remain inside persistence adapters.

## SQLite vs PostgreSQL

- SQLite plus `SqlAlchemyVectorStore` is the default local/demo path. It persists JSON vectors and
  computes cosine similarity in process.
- PostgreSQL plus `PgVectorStore` is the production-like development path. It persists embedding
  metadata in `embeddings`, stores the vector only in `rag_vectors.embedding`, and ranks with
  pgvector's cosine-distance operator.

There is no connection probing or automatic fallback. An explicit PostgreSQL URL that is malformed,
unreachable, or unable to initialize pgvector fails startup.

## Configuration and driver

The supported asynchronous PostgreSQL URL form is:

```text
postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/DATABASE
```

`asyncpg` is the existing SQLAlchemy driver. Engines use `pool_pre_ping`; request, worker, and
repository sessions are context-managed, failed transactions roll back, and application shutdown or
failed startup disposes the engine.

The default production-like Compose runtime exposes the same URL through `DATABASE_URL_FILE`. A
one-shot, no-network initializer generates the password and encoded DSN in a named volume;
PostgreSQL consumes `POSTGRES_PASSWORD_FILE`, API reads the DSN file, and Web receives neither.
Direct `DATABASE_URL` remains the non-Docker/test compatibility entry. Configuring direct and file
forms together fails closed.

Unlike the disposable `compose.postgres-test.yaml` service below, production-like `compose.yaml`
does not publish port 5432 and stores PostgreSQL data in a named volume. Normal restart, image
rebuild, and `compose down` preserve that volume. Deletion requires the explicit project-scoped
purge workflow documented in `docs/CONTAINER_RUNTIME.md`.

## Schema initialization

Fresh startup runs SQLAlchemy `create_all`, the existing small pre-Alembic compatibility migrations,
and the idempotent pgvector initializer. Repeated startup does not delete application data. The
initializer:

1. executes `CREATE EXTENSION IF NOT EXISTS vector`;
2. creates `rag_vectors` with a foreign key to `chunks`;
3. verifies or safely converts the vector type modifier to the configured dimension;
4. creates `ix_rag_vectors_embedding_hnsw` with `vector_cosine_ops`.

The project still has no formal Alembic baseline. Introducing one before further production schema
evolution remains future work.

## Embedding dimension and vector storage

The dimension contract comes from the active `EmbeddingProvider`. Both the deterministic local
provider and the OpenAI adapter use 256 dimensions, so the PostgreSQL column is `vector(256)`.
OpenAI requests native `dimensions=256`; it does not slice a larger vector. `PgVectorStore` accepts dimensions from 1 through 2000, matching
the HNSW `vector` index limit, and validates every write and query before SQL execution.

A mismatch or non-finite value produces a clear application error. During ingestion it becomes a
terminal failed job, staged chunks are removed, and the prior completed generation remains active.
Changing provider dimensions requires a compatible schema transition and knowledge re-ingestion; it
does not silently compare incompatible vectors.

On PostgreSQL, `embeddings.vector_json` is deliberately `NULL`; the actual embedding exists in the
pgvector column. This prevents the portable fallback representation from being mistaken for the
PostgreSQL retrieval path.

## Retrieval semantics and index

PostgreSQL semantic search orders by cosine distance (`<=>`) and converts it at the adapter boundary:

```text
application_score = 1 - cosine_distance
```

Higher application scores are therefore better on both SQLite and PostgreSQL. Tests compare the
PostgreSQL result with the application cosine implementation without asserting a fragile exact
floating-point constant.

Hybrid retrieval remains application-owned:

```text
combined_score = 0.82 * max(cosine_score, 0) + 0.18 * lexical_score
```

The HNSW cosine index is created and catalog-verified. Tests intentionally do not require a specific
`EXPLAIN` plan because PostgreSQL may correctly choose a sequential scan for small corpora.

## Completed-only RAG and ingestion concurrency

Semantic SQL, lexical candidates, hybrid ranking, and citation hydration all join the owning
`IngestionJob` and require `completed`. Real PostgreSQL tests cover successful ingestion, vector
failure, activation failure after vector write, dirty failed rows, old-generation preservation, and
successful replacement.

Job claiming locks the document row with `SELECT ... FOR UPDATE`; two jobs for the same document
cannot both become processing. The local queue remains a single-process adapter. Distributed and
multiprocess delivery are not tested and still require a durable broker/lease design.

## Transaction isolation and Memory locking

Tests confirm PostgreSQL's current `READ COMMITTED` isolation level. Memory settings changes and Run
finalization lock the same Agent row with `SELECT ... FOR UPDATE` and hold it through commit.

Real independent connections and deterministic interleavings validate:

- disable commits first: finalization sees disabled and writes no durable Memory/event;
- finalization commits first: Memory, `memory.written`, terminal event, and completed Run commit
  atomically before disable proceeds;
- two concurrent complete Runs deduplicate the same canonical fact without leaking an integrity
  error;
- a terminal event constraint failure rolls back Memory and terminal Run state together.

## Evaluation, Observability, and data compatibility

PostgreSQL integration verifies Suite/Case CRUD and executes Calculator Evaluation cases (`5192`
PASS and `9999` FAIL). It covers idempotent starts, Evaluation Memory isolation, Dashboard
`run_kind` isolation, persisted case/grader aggregates, rollback of every aggregate field after an
injected PostgreSQL transaction failure, Run/RunEvent metrics, tool correlation, durations, and
recursive redaction before persistence. UUID strings, timezone-aware timestamps, JSON text
envelopes/metadata, nullable values, and critical unique constraints traverse real PostgreSQL in
these workflows.

## Test infrastructure and safety

`compose.postgres-test.yaml` runs only `pgvector/pgvector:pg17`, binds to
`127.0.0.1:55432`, uses a healthcheck, and stores the database in container tmpfs. Stopping/removing
the service deletes all test data.

```powershell
$env:POSTGRES_TEST_PASSWORD = "local-integration-only"
docker compose -f compose.postgres-test.yaml up -d --wait

$env:POSTGRES_TEST_DATABASE_URL = "postgresql+asyncpg://agent_studio_test:local-integration-only@127.0.0.1:55432/agent_studio_test"
$env:POSTGRES_NO_VECTOR_TEST_DATABASE_URL = "postgresql+asyncpg://agent_studio_limited_test:not-a-secret-test-only@127.0.0.1:55432/agent_studio_no_vector_test"
$env:POSTGRES_TEST_ALLOW_DESTRUCTIVE_RESET = "I_UNDERSTAND_THIS_DROPS_TEST_TABLES"
.\.venv\Scripts\pytest.exe apps/api/tests/postgres -q

docker compose -f compose.postgres-test.yaml down
```

The second credential is an intentionally public, disposable negative-test credential created only
inside the loopback tmpfs container. The destructive reset helper does not read `DATABASE_URL`. It
accepts only explicit PostgreSQL+asyncpg test URLs whose host is loopback and whose database and role
both end in `_test`; it requires the exact destructive-reset confirmation above and verifies
`current_database()` and `current_user` again before dropping tables.

## Failure and security behavior

- PostgreSQL unavailability never creates or opens the SQLite fallback.
- Database configuration accepts only `sqlite+aiosqlite` and `postgresql+asyncpg`; other backends or
  sync/wrong drivers fail closed before engine construction.
- Missing permission to create/use pgvector fails startup with a bounded configuration message.
- `/health` performs `SELECT 1` and returns a safe 503 if an established backend becomes unavailable.
- User filters, ID lists, vectors, and limits are bound parameters. The only interpolated vector type
  modifier is the validated, provider-owned integer dimension.
- Secret-shaped Run/RunEvent/Evaluation values are redacted before persistence.
- Failed ingestion cleanup cannot make staged or failed generations retrievable.

## Performance sanity

The optional PostgreSQL suite inserts, indexes, activates, and retrieves 1000 deterministic chunks
inside a bounded test. This is a connection/leak and obvious-complexity sanity check, not a benchmark
or load test. Query-plan and large-corpus tuning belong to later performance work.

## Validated and remaining limits

Validated in Task 10: PostgreSQL 17, pgvector extension/version discovery, fixed vector storage,
semantic/hybrid RAG, metadata filters/citations, HNSW presence, completed-only generations, real row
locks, concurrent Memory dedupe, Evaluation, Observability, redaction, SQLite compatibility, and full
browser E2E on both database backends.

Still not tested by default: Real OpenAI/online embeddings (an explicit opt-in integration test is
provided), distributed workers, production TLS, managed
PostgreSQL, backup/restore, cloud IAM/database roles, multi-tenancy/RBAC, and production load. The
test superuser and disposable credentials are not a production role design.
