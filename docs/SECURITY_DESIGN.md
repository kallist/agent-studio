# Security Hardening v1

## 1. Scope

This design secures Agent Studio's implemented local-workbench attack surface: agent context
construction, the bounded runtime, tools, Calculator, knowledge ingestion and retrieval, durable
Memory, Evaluation, persistence, REST, SSE, observability, and React rendering. It does not add a
network tool, code executor, shell, authentication, multi-tenancy, or external security service.

Security claims in this document apply to application-owned boundaries and deterministic tests.
They do not claim that a probabilistic model can never repeat text it was legitimately shown.

## 2. Threat model

The attacker can submit prompts and JSON bodies, upload supported documents with hostile content
or filenames, choose public IDs and filters, configure Evaluation definitions, and disconnect or
consume SSE slowly. The attacker may place prompt-injection text, HTML/JavaScript-looking strings,
false provenance labels, SQL syntax, secret-shaped values, oversized content, and malformed types
in these inputs.

Protected assets are server-owned instructions and configuration, provider credentials, tool
permissions, object relationships, durable Memory namespaces, knowledge provenance and generation
visibility, persisted Run/Trace/Evaluation evidence, local files, database integrity, API/worker
availability, and browser execution integrity.

The local process, server-owned registry, validated application configuration, repository code,
and domain contracts are trusted. Provider/SDK output is not trusted merely because it came from a
provider. The local machine and database administrator remain outside this threat model.

## 3. Trust boundaries

| Boundary | Classification | Rule |
| --- | --- | --- |
| Application control instructions | Trusted | Created and owned by server code. |
| Validated Agent configuration | Trusted configuration | May supply Agent instructions only after application validation. |
| ToolRegistry, permissions, domain contracts | Trusted | Models cannot register or grant tools. |
| User prompt and JSON/query/path input | Untrusted data | Typed, length-bounded, and never promoted by retrieval. |
| Document bytes, filename, extracted text, chunks | Untrusted data | Validated, bounded, and stored with server-generated paths/provenance. |
| RAG results and metadata | Untrusted data | Evidence only; never system/developer instructions. |
| Durable Memory and metadata | Untrusted data | Policy-gated data in a dedicated runtime field. |
| Evaluation input, expected values, setup | Untrusted data | Structured allowlists only; no executable grader/setup. |
| Tool input/output and provider/SDK output | Untrusted data | Schema/size validated and error-normalized. |
| Event payload and UI text | Untrusted data | Redacted, size-bounded, JSON serialized, and rendered as React text. |

RAG CONTENT IS DATA. MEMORY CONTENT IS DATA. USER INPUT IS DATA.

## 4. Prompt injection

`AgentContext` keeps Agent instructions separate from `user_input`, `memory`, tool specifications,
and prior steps. The OpenAI adapter gives instruction authority only to application control text and
the validated Agent instructions. Its serialized per-step context is one untrusted data object and
explicitly names user input, Memory, RAG/tool results, metadata, and provider output as data that
cannot grant permissions or override control rules.

The deterministic Mock path uses the same bounded `AgentLoop`, tool allowlist, permissions, schemas,
duplicate protection, and limits. Structural regression tests inspect the context boundary without
asking a real model to decide whether an injection succeeded.

## 5. Indirect prompt injection

Hostile instructions retrieved from RAG or Memory remain in their structured data locations. They
are never concatenated into the application control prompt. Retrieval may return and display the
hostile text because inspection is a product feature; that does not grant the text instruction
authority. Tests cover instruction-like Memory, a document requesting system-prompt disclosure,
and the absence of invented tools or server instruction serialization.

## 6. RAG trust model

Document content cannot supply `document_id`, `chunk_id`, filename, source URI, page, generation, or
score. Citations hydrate these values by joining server persistence. Text such as `SOURCE:
trusted-policy.pdf` remains chunk content and cannot change real provenance. Retrieval independently
requires the owning ingestion job to be `completed`; queued, processing, failed, orphaned, and
staged generations are invisible. Previous completed generations survive failed replacement.

Knowledge poisoning (false facts) is distinct from prompt injection. v1 preserves provenance and
inspection but does not moderate or prove factual truth.

## 7. Memory trust model

Every application-owned durable write path uses `MemoryPolicy`. Stable facts and explicit remember
requests are bounded, normalized, screened for secret/instruction shapes, scoped by Agent, and
deduplicated by `(agent_id, normalized_key)`. Evaluation setup uses the same content gate and cannot
name an Agent or Memory namespace. Retrieval has Agent scope, expiration, relevance threshold, five
results, and a 1,500-character context budget. A defensive test can inject a hostile record behind
the persistence seam to prove that retrieval still treats it as data.

The serialized settings/finalization transaction and disable-wins/finalization-wins invariants are
unchanged.

## 8. Tool security

Tool names resolve only through the server-owned registry and must also be enabled on the Agent.
Arguments are JSON, byte-bounded, and validated by Pydantic; Calculator forbids extra fields.
Permissions fail closed. Each definition has a timeout, input and output limit, and output schema.
The AgentLoop bounds steps, total time, decision size, consecutive duplicates, and calls per tool.
Unknown or disabled tools, including `delete_database`, fail without handler execution. Exceptions
become controlled `ToolExecutionError` summaries.

Calculator parses an expression AST and implements only numeric constants, `+`, `-`, `*`, `/`,
unary signs, and parentheses. It never calls `eval`, `exec`, `compile`, a shell, filesystem API, or
Python builtins. Attribute access, calls, lambdas, comprehensions, containers, names, and other
syntax are rejected. `128 * 37 + 456` remains `5192`.

SSRF through an Agent HTTP tool: **NOT APPLICABLE / TOOL NOT IMPLEMENTED**.

## 9. File ingestion

Uploads are read to `KNOWLEDGE_MAX_FILE_BYTES + 1`. Filenames are Unicode-normalized, limited to 255
characters, restricted to a basename, and reject separators, control/NUL characters, and encoded
separator/traversal tokens. Storage uses a generated UUID filename below a resolved application
root; a containment check runs before writing. User filenames are display metadata only.

The extension/MIME allowlist supports `.txt`, `.md`, and `.pdf`. Text must decode as UTF-8 and may
not contain NUL bytes. PDF content must start with `%PDF-`; strict parsing rejects corruption,
encryption, empty/image-only documents, and more than 500 pages. Parser exceptions fail only the
job. Extraction is off the event loop and has a timeout, extracted-character limit, chunk limit,
and bounded heading metadata. Failed/staged chunks remain unretrievable.

Local thread timeouts free the ingestion worker but cannot forcibly terminate a Python thread that
is stuck in native parser code. A process-isolated production parser is future work.

## 10. Database

User values use SQLAlchemy expressions or named bind parameters. The pgvector query builds SQL only
from server-owned fixed clause strings; values, expanded ID lists, filters, vectors, and limits are
bound. There is no user-selectable sort column, raw SQL fragment, table name, or dynamic identifier.
Targeted `' OR 1=1 --` and `DROP TABLE` strings remain filter data.

Run/Agent kind, Evaluation source/clone, CaseResult/EvaluationRun, AgentRun/evaluation Agent, Memory
Agent, knowledge-base attachment, and citation/document relationships are validated. These are
domain integrity controls, not multi-tenant authorization.

## 11. XSS and Markdown

Final output, tool details, citations, Memory, Evaluation values/evidence, generic events, filenames,
metadata, and errors render through normal React text children or JSON text. The application has no
`dangerouslySetInnerHTML` and no Markdown/raw-HTML renderer. Strings containing `<script>`, event
handler attributes, `javascript:` or `data:` remain inert text; they are not converted to links or
elements. Vitest and Playwright assert that `window.__xss` is not set.

Markdown rendering: **NOT APPLICABLE / NOT IMPLEMENTED**. Uploaded Markdown is parsed for headings
and displayed as plain extracted text.

## 12. SSE

Event names accept only 1-40 ASCII letters, digits, dots, underscores, and hyphens, preventing typed
event framing injection. Payloads are redacted and byte-bounded before persistence/publication, then
serialized with `json.dumps`; embedded newlines or `event:`/`data:` strings remain escaped JSON.
Every event is mirrored on `agent.event`; clients deduplicate by application event ID.

Subscriber queues are bounded. They are wake-up signals only: after every wakeup the stream reads
ordered events from persistence, so slow consumers can catch up without an unbounded in-memory queue.
The cursor is non-negative and bounded.

## 13. Evaluation

`GraderType` is a closed enum. Setup accepts only bounded Memory seeds, with no code, shell, SQL,
regex execution, imports, module/class names, or paths. `os.system` fails request validation.
Evaluation clones must originate from a normal source Agent; their Runs must use `run_kind=evaluation`
and relationship checks prevent mixing another EvaluationRun, clone, or Run. Clones reuse knowledge
read-only and receive unique Memory namespaces. They cannot be used as a new Suite source or normal
Run target, and Evaluation traffic remains outside normal Dashboard metrics.

## 14. Secrets and redaction

Provider keys come only from settings and no configuration endpoint exposes them. OpenAI without a
key returns the explicit configured-state error and never falls back to Mock. Structured payloads
recursively redact authorization, API-key, access/refresh-token, password, secret, cookie, and
set-cookie key variants. Free text redacts labelled values, Bearer credentials, credential-like Basic
values, and `sk-...` shapes without deleting ordinary prose containing the word `token`.

The exact sanitized event is persisted and published. Repositories sanitize again, Run errors use
text redaction, and Evaluation actual/evidence/reasons are redacted. Real secrets must never be used
as Agent Studio inputs or committed to the repository.

## 15. Error handling and logging

Expected application errors are controlled messages. Unexpected provider, runtime, persistence, and
Evaluation errors return generic bounded summaries. Python traceback, provider exception text,
environment values, SQL details, and local paths stay out of REST, SSE, Trace, and Evaluation.
Server logs retain stack traces for debugging but log IDs rather than prompts, Memory bodies,
documents, credentials, or database URLs. Redaction is defense in depth, not permission to log
sensitive values.

Container runtime logs remain stdout/stderr at INFO with bounded Docker rotation. Verbose provider
SDK diagnostics are off. Database URLs, runtime-secret contents, Authorization values, user/RAG/
Memory bodies, and provider payloads are not startup or health log fields.

### Container runtime trust boundary

The production-like Compose topology binds Web/API host ports only to loopback and does not publish
PostgreSQL. Web and API share an app network; API and PostgreSQL share a separate internal network.
Web receives neither the DB runtime-secret volume nor provider-secret volume. API/Web are stable
non-root users with all Linux capabilities dropped, no-new-privileges, read-only roots, bounded
`/tmp`, no host networking, no privileged mode, no source bind mount, and no Docker socket.

A no-network one-shot initializer creates the project-scoped PostgreSQL password and password-bearing
DSN in a Docker named volume; DB/API mount it read-only. For provider profiles, the helper sends the
selected host key to a no-network initializer over stdin; that removed-after-use container writes a
separate project volume mounted read-only only by API. The value is not stored in image layers,
Compose source, command arguments, or persistent container environments. Direct values and
corresponding `*_FILE` settings are mutually exclusive. Missing, empty, unreadable, oversized, or
ambiguous files fail without echoing content. This is local secret isolation, not a cloud
secret-manager design.

## 16. Resource limits

| Input/work | Bound |
| --- | --- |
| Run prompt | 20,000 characters |
| Agent instructions | 8,000 characters |
| AgentLoop | 3 steps, 30 seconds, 3 calls/tool by default |
| Runtime context / decision | 32,000 / 8,000 characters by default |
| Tool input | 16,000 UTF-8 bytes by default |
| Calculator expression | 200 characters |
| Knowledge query / top-k | 4,000 characters / 1-20 |
| Upload | 10 MiB default, hard setting ceiling 50 MiB |
| Extracted text / PDF pages | 2,000,000 characters / 500 pages default |
| Chunks / parser time | 5,000 / 15 seconds default |
| Tool output / event payload | definition-specific / 256,000 bytes |
| Durable Memory | 500-character write, 5 results, 1,500-character context |
| Evaluation | 200 Cases/Suite, 30 graders/Case, 10 Memory seeds/Case |
| Workers | 1 default, configuration ceiling 8 |
| SSE subscriber queue | 256 wake-up events |

These are per-request/per-run bounds. v1 does not implement global rate limiting or a durable broker.

## 17. CORS, hosts, network exposure, and CSRF

FastAPI defaults to the two local web origins, credentials disabled, four required methods, and two
required request headers. Wildcard origins are not the default. Host validation defaults to
`127.0.0.1`, `localhost`, and test hosts. README launch commands bind both services to `127.0.0.1`.
The default is a local workbench, not a public network service.

FastAPI and Next.js add `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`X-Frame-Options: DENY`, and a restrictive `Permissions-Policy`. A deployment-specific CSP is
deferred because Next development/build scripts require a tested nonce/hash strategy; an untested
static CSP would risk breaking the app.

Authenticated CSRF: **NOT APPLICABLE** because there is no cookie authentication. If cookie auth is
added, same-site cookies, origin checks, and CSRF tokens become required.

## 18. Secure defaults

Mock is deterministic and keyless. OpenAI and OpenAI embeddings are explicit opt-ins. SQLite is the
local fallback. Hosts/origins and uploads are restricted, storage names are generated, tools and the
loop are bounded, and unsafe content remains data. No hidden environment variable is required to
turn these controls on.

## 19. Testing

Backend tests cover context separation, RAG/Memory injection seams, hallucinated and repeated tools,
Calculator code syntax, traversal/MIME/PDF cases, failed-generation visibility, spoofed provenance,
SQL strings, redaction before DB/REST/SSE/Evaluation, safe unexpected errors, illegal graders,
Evaluation/Memory/Dashboard isolation, relationship checks, validation fuzz cases, and resource
bounds. Frontend tests cover hostile output, citations, Memory, grader evidence, generic events, and
errors. Playwright covers real XSS/Memory rendering, RAG injection/provenance, illegal Evaluation
grader rejection, and the existing Calculator/RAG/Memory/observability/evaluation/mobile flows.

Real OpenAI behavior: **NOT TESTED** by the default suite.

The Agents SDK is pinned and receives `tracing_disabled=true` by default plus
`trace_include_sensitive_data=false` explicitly. Provider keys are passed only to SDK clients and
never enter instructions, input, persisted events, API responses, or UI state. The adapter sets
`store=false`, uses no hosted session and no `previous_response_id`, and applies bounded output,
timeout, and retry settings.

Live PostgreSQL/pgvector behavior is tested with bound injection-shaped filters, fixed-dimension
vector writes, completed-only retrieval, redaction before Run/RunEvent/Evaluation persistence, a
loopback/disposable test database guard, explicit unavailable-database failure, and an independent
role that cannot create the vector extension. TLS, managed-database IAM, at-rest encryption, backup
policy, and production database roles remain **NOT TESTED**.

## 20. Known limitations

- Authentication: **NOT IMPLEMENTED**.
- Authorization / RBAC: **NOT IMPLEMENTED**.
- Multi-tenancy: **NOT IMPLEMENTED**.
- The API is unsuitable for untrusted shared-network exposure.
- No global/user rate limiting, quota, WAF, SIEM, Vault, or external secret manager is implemented.
- In-process ingestion/Evaluation queues are single-process adapters, not durable brokers.
- Parser timeout cannot kill a stuck native parsing thread; production should isolate parsing in a
  resource-limited process/container.
- Knowledge content can be false or malicious; provenance does not prove truth.
- A model may repeat contextual text it was shown. The application prevents direct serialization of
  its private control prompt and prevents data from gaining application/tool authority.
- A deployment CSP, TLS/HSTS, backup encryption, database roles, and production retention policies
  depend on a concrete deployment and remain unimplemented.

## 21. Future authentication, RBAC, and multi-tenant work

Before any shared deployment, add authenticated identities, tenant IDs to every repository key and
vector/Memory query, deny-by-default object authorization, RBAC for tools and administration,
session/CSRF policy, audit retention, rate limits, encrypted secret storage, migration-managed
database roles, and cross-tenant isolation tests. These capabilities must not be inferred from the
current object-integrity checks.
