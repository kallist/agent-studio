# Knowledge Base and RAG design

## Scope

This slice implements application-owned knowledge ingestion, vector retrieval, agent tool access, and citation inspection. It follows `docs/ARCHITECTURE.md`: knowledge orchestration is a service, embeddings and vector search are ports, persistence is an adapter, HTTP handlers stay thin, and provider SDK types do not cross the `AgentRuntime` boundary.

The default path is fully runnable without an API key:

- SQLite persists knowledge metadata, chunks, and deterministic local vectors.
- `LocalIngestionWorker` processes jobs outside the upload request.
- `DeterministicEmbeddingProvider` supports tests, demos, and the miniature benchmark.
- PostgreSQL URLs select `PgVectorStore`, which enables `pgvector` and performs cosine ranking in SQL.

OpenAI embeddings are opt-in through `EMBEDDING_PROVIDER=openai` and `OPENAI_API_KEY`. The provider uses the configured `OPENAI_EMBEDDING_MODEL`; the default is `text-embedding-3-small`.

## Data model

`KnowledgeBase` records the active embedding provider/model so incompatible query vectors are never silently compared. `Document` stores the safe display filename, source URI, verified MIME type, byte size, and an opaque generated storage path. `Chunk` owns ordered text plus parser/chunk metadata and is tied to the `IngestionJob` generation that produced it. `Embedding` owns provider/model/dimensions metadata and the portable fallback vector. `IngestionJob` records `queued`, `processing`, `completed`, or `failed`, with timestamps and a bounded user-safe error.

Agents persist attached knowledge-base IDs and enable the stable tool name `knowledge_search`. The runtime adds those IDs server-side; a model cannot choose arbitrary collections by supplying hidden tool arguments.

## Ingestion flow

1. The API reads at most `KNOWLEDGE_MAX_FILE_BYTES + 1` bytes.
2. It validates filename, extension, reported MIME, content signature/encoding, and size.
3. It writes to a generated UUID path under `KNOWLEDGE_STORAGE_PATH` and creates a `Document` plus `queued` job.
4. The API returns HTTP 202 immediately.
5. A bounded in-process worker claims the queued job, parses, chunks, and computes embeddings. PostgreSQL serializes claims with a document row lock; SQLite uses one conditional `UPDATE ... RETURNING` claim so concurrent local workers cannot both own the same document.
6. New chunks are staged under that job generation and remain invisible while vectors are upserted.
7. One database transaction activates the generation: it removes the prior completed generation, normalizes chunk order, and marks the job `completed`.
8. Parsing, embedding, staging, vector upsert, and activation share one orchestration failure boundary. A failure marks only the current queued/processing job `failed`, then removes that generation's staged vectors; terminal jobs are never rewritten by cleanup. A previous completed generation remains available.
9. On process startup, abandoned `processing` jobs return to `queued`; retry replaces that job's hidden staging data before activation. Duplicate delivery of a terminal job is an idempotent no-op, and two jobs for one document are not allowed to process concurrently.

Retrieval independently joins every semantic, lexical, and citation-hydration candidate to its owning ingestion job and requires `completed`. This is the second integrity boundary: staged, queued, processing, failed, legacy-ambiguous, and orphaned vector records cannot become citations even if cleanup is interrupted.

The worker is intentionally behind a small `enqueue/start/stop` boundary. A durable queue can replace it without changing routes, parsers, retrieval, or the data model. The local queue is suitable for one API process; see limitations below.

## File parsing and security

Supported inputs are:

| Format | Canonical MIME | Parser behavior |
| --- | --- | --- |
| `.txt` | `text/plain` | UTF-8/UTF-8-BOM text |
| `.md` | `text/markdown` | UTF-8 text split into heading-aware sections |
| `.pdf` | `application/pdf` | `pypdf` text extraction with page metadata |

Controls include:

- 10 MiB default size limit, configurable by environment;
- basename-only normalized filenames, control-character rejection, and generated storage names;
- allowlisted extensions and MIME pairs;
- `%PDF-` signature checking, UTF-8 validation, and NUL-byte rejection;
- encrypted PDF rejection and a 500-page ceiling;
- no user-controlled storage paths;
- parser work moved off the event loop;
- parser exceptions contained at the job boundary and returned as bounded, non-sensitive failures.

PDF extraction is text-only. Scanned/image-only PDFs fail with an explicit OCR-not-enabled message. This is intentional: adding OCR would add operational cost and a larger attack/dependency surface.

## Chunk strategy

`TextChunker` is paragraph and sentence aware:

- target: 900 characters;
- overlap: 140 characters;
- preferred boundaries: blank line, sentence ending, then newline;
- Markdown headings remain section metadata;
- PDF pages remain page metadata;
- every chunk records source-relative character offsets and an approximate token count.

The character-based strategy is provider-neutral and avoids a tokenizer dependency. The overlap protects facts that cross boundaries. It is deliberately small enough for citation inspection and large enough to preserve local context. Future measurements may justify a model tokenizer or semantic segmentation, but the benchmark should drive that change.

## Embedding abstraction

`EmbeddingProvider` exposes `name`, `model`, `dimensions`, and async batch `embed`. Two adapters exist:

- `DeterministicEmbeddingProvider`: signed feature hashing over word, CJK bigram, and character-trigram features. It is stable, local, inexpensive, and useful for deterministic tests. It is not claimed to match production neural semantic quality.
- `OpenAIEmbeddingProvider`: async batched calls through the official OpenAI client. It is opt-in and never required for the main tests.

`VectorStore` owns initialization, upsert, deletion, and filtered similarity search. SQLite uses a persisted-vector fallback with in-process cosine ranking. PostgreSQL uses a separate `rag_vectors` table with the `vector` type and the `<=>` cosine-distance operator. No pgvector operator crosses into the service or domain contracts.

## Retrieval algorithm

Semantic retrieval embeds the query, filters by knowledge-base and optional exact `document_id`, `source`, or `filename`, then ranks by cosine similarity. `top_k` is constrained to 1-20.

Hybrid retrieval is enabled by default. It obtains a wider semantic candidate list, computes a lightweight lexical overlap score using word and CJK-bigram terms, and ranks the union with:

```text
combined_score = 0.82 * max(cosine_score, 0) + 0.18 * lexical_score
```

The response always names the algorithm and returns the final score. This modest lexical component improves exact identifiers and policy wording without introducing a search engine dependency. It is not a full BM25 implementation.

## Agent tool and citations

`KnowledgeSearchTool` is an application adapter registered as `knowledge_search`. Its public arguments are query and `top_k`; attached collection IDs are bound server-side in an async task-local run scope. The input schema forbids undeclared fields, so a provider cannot supply arbitrary collection IDs. The registry definition declares `knowledge:read`, a 15-second timeout, a 100 KB serialized output limit, and `KnowledgeSearchResponse` as its output schema. `ToolExecutor` performs input/output validation, permission enforcement, timeout, size enforcement, and error normalization before producing `ToolResult`.

The structured result contains:

- document ID and display name;
- chunk ID and ordered chunk index;
- source URI;
- retrieval score;
- chunk text;
- parser/chunk metadata, including PDF page or Markdown heading when present.

Both `MockRuntime` and `AgentsSdkRuntime` use the hardened application-owned `AgentLoop`. A successful search follows `AgentLoop -> ToolExecutor -> ToolResult -> AgentStep`, and the normalized `tool.completed` event stores the validated output at `payload.result`. Citations remain at `payload.result.results`; the frontend renders document, chunk, source, score, content, and page metadata from that normalized shape.

## Miniature benchmark

`tests/fixtures/rag/` contains two relevant source documents, three distractor documents, and `benchmark.json`. The automated benchmark ingests the real fixtures, runs three questions in both semantic and hybrid modes, requires the identified document/chunk at the declared rank (currently top-1), and computes deterministic Recall@3 against a 1.0 floor. Additional tests cover:

- semantic-only retrieval, `top_k`, and metadata filters;
- queued ingestion through terminal state;
- real PDF text extraction with retained page metadata;
- filename/path traversal, unsupported extension, MIME mismatch, invalid PDF signature, and binary-text rejection;
- parser crash isolation;
- vector-write failure after chunk generation with no retrieval result or tool citation;
- failed replacement preserving the last completed generation;
- hidden staged data across a simulated worker crash and successful restart recovery;
- activation failure after successful vector upsert, worker terminal handling, old-generation preservation, cleanup, and subsequent successful re-ingestion;
- terminal duplicate delivery and true two-worker SQLite duplicate-job protection;
- deliberately retained failed chunk/vector rows remaining invisible to lexical, semantic, hybrid, and citation hydration;
- HTTP-boundary oversized-file rejection;
- recovery of both queued and abandoned processing jobs without accumulating duplicate chunks;
- the concrete `knowledge_search` schema, permission, timeout, output-limit, and error contract;
- the full mock Agent path through `AgentLoop`, `ToolExecutor`, normalized trace, and final answer with complete citation provenance.

This is a regression benchmark, not a statistically meaningful retrieval evaluation. Add cases and metrics such as Recall@K or MRR before tuning weights or chunk sizes.

## API surface

- `POST /knowledge-bases`
- `GET /knowledge-bases`
- `GET /knowledge-bases/{id}`
- `GET /knowledge-bases/{id}/documents`
- `POST /knowledge-bases/{id}/documents` (multipart, returns 202)
- `GET /ingestion-jobs/{id}`
- `POST /knowledge-bases/{id}/search`

## Limitations and next steps

- The local worker is process-local. Within one shared database, PostgreSQL document-row locking and the SQLite atomic conditional claim prevent two workers from processing one document concurrently. Multiple API replicas still need a durable broker with delivery guarantees, bounded retries, and operational reconciliation.
- Local file storage is not shared or transactional with the database. Production should use object storage plus cleanup/reconciliation jobs.
- SQLite cosine search loads candidate vectors into the API process and is intended only for local/demo scale.
- The pgvector adapter has no ANN index yet. Its completed-generation SQL predicate has a construction-level regression test, but a live PostgreSQL/pgvector integration was not added by this fix. Add HNSW/IVFFlat only after corpus and latency measurements justify it.
- The pre-Alembic startup migration bridges the agent attachment column and adds/backfills `chunks.ingestion_job_id`. Legacy chunks are exposed only when the newest known job completed; ambiguous failed/processing replacements remain hidden. Establish Alembic before further production schema evolution.
- There is no OCR, table-aware PDF parsing, deduplication, public document deletion/re-ingestion endpoint, or tenant authorization yet. The generation model and tests cover replacement consistency before that endpoint is introduced.
- Hybrid lexical scoring is simple overlap rather than BM25 and uses fixed weights.
- OpenAI embedding batching has no retry/rate-limit policy yet; a production queue should add bounded retries and dead-letter handling.
- Knowledge-base attachment is stored on an agent definition but not versioned separately in this first slice.
