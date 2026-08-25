# CI, reliability, performance, and delivery foundation

## 1. Goals

Task 13 makes the existing product quality contract repeatable on GitHub-hosted runners. It adds
offline-by-default pull-request gates, real PostgreSQL/pgvector integration, production image and
runtime checks, bounded reliability scenarios, a synthetic performance baseline, and delivery-ready
evidence. It does not deploy to the internet or publish an image.

## 2. CI architecture

`.github/workflows/ci.yml` runs independent Backend, PostgreSQL, Frontend, Playwright, Docker,
Reliability, and Performance jobs. A new commit cancels an older run for the same pull request;
main runs use unique groups and are never cancelled by a later main run. Every job has an explicit
timeout and the workflow default permission is `contents: read`.

The workflows use maintained major tags for official `actions/*` and `pnpm/action-setup` actions.
Major tags receive compatible security fixes without embedding stale commit SHAs; updates remain
reviewable through the workflow diff and dependency audit.

## 3. Pull-request gates

- Backend: Python 3.12 clean install, `pip check`, offline pytest, Ruff, strict mypy, repository
  safety validation, and `pip-audit`.
- PostgreSQL: the existing guarded real-database suite on PostgreSQL 17 + pgvector 0.8.6.
- Frontend: Node 24, pnpm 10.18.2 frozen install, Vitest, TypeScript, ESLint, webpack production
  build, and production dependency audit.
- Playwright: the full deterministic Mock-only browser suite with health-based webServer readiness.
- Docker: Compose validation and clean production API/Web image builds.
- Reliability: selected deterministic application tests plus project-scoped container restart and
  persistence validation.
- Performance: the explicit synthetic PostgreSQL/pgvector benchmark and catastrophic-regression
  policy.

Independent jobs continue after another job fails so one run reports all broken subsystems.

## 4. Main gates

`ci.yml` repeats core quality gates on a push to main. `delivery.yml` additionally builds and runs
production images from fresh project-scoped volumes, exercises Calculator, Memory, RAG, Evaluation,
restart persistence, and full container-targeted Playwright, then emits delivery metadata. It runs
on pull requests so the exact delivery job is validated before merge, repeats automatically on main,
and remains manually dispatchable after the workflow exists on the default branch.

## 5. PostgreSQL CI

CI reuses `compose.postgres-test.yaml`, `infra/postgres-test-init.sql`, and the Task 10 pytest
fixtures instead of inventing another database topology. The service is loopback-only, tmpfs-backed,
and named with an `agent-studio-task13-*` project. Reset still requires the exact confirmation and
accepts only loopback `postgresql+asyncpg` URLs whose database and role end in `_test`.

Tests inspect the real vector extension, `vector(256)` column, HNSW index, completed-only RAG,
semantic/hybrid retrieval, PostgreSQL row locking, concurrent Memory dedupe, Evaluation,
Observability, redaction, and unavailable-database failure. Real-provider tests are deselected.

## 6. Frontend CI

The lockfile is authoritative. CI never uses `--no-frozen-lockfile` and caches only the pnpm store.
The production build explicitly uses webpack, matching the Task 12 Docker image.

## 7. Playwright

`playwright.ci.config.ts` is the Linux runner configuration. It starts the real FastAPI and Next.js
development servers, polls their URLs through Playwright `webServer`, and clears provider keys.
There is no fixed startup sleep. Traces and screenshots are retained only for failed tests and are
uploaded for five days; video is disabled.

`playwright.docker.config.ts` targets the running production Compose stack in delivery validation.

## 8. Docker build validation

The Docker job parses Compose, builds both production Dockerfiles from a clean checkout, and checks
the fixed non-root users. Reliability and Delivery then run those images. No host `node_modules`,
virtualenv, source bind mount, or developer database participates in the build.

## 9. Continuous delivery definition

`DELIVERY READY` means the SHA's production images built and its disposable Compose runtime passed
the documented smoke and E2E checks. It does not mean deployed. Task 13 does not push Docker Hub,
GHCR, a private registry, a release, or any cloud/public target.

The delivery artifact contains only git SHA, UTC timestamp, image identities, safe result names,
and timings. It contains no environment dump, database URL, credential, data body, or trace.

## 10. Secret model

Normal CI explicitly sets both real-provider flags to `0` and both provider keys to empty strings.
It uses no `pull_request_target`, Environment, production secret, or write permission. Disposable
test database credentials are fixed non-production values whose service is loopback-only and whose
data is removed after the job.

## 11. Optional real-provider validation

`provider-live.yml` is manual-only, binds the protected `provider-live-validation` Environment,
requires its DeepSeek secret, and runs only the explicit billable DeepSeek suite. It is not a merge
gate. No ordinary pull request or main workflow references that secret. Real OpenAI remains outside
Task 13 validation.

## 12. Reliability model

`pytest.mark.reliability` selects bounded tests for Run terminal state/event ordering, concurrent
Calculator runs, cancellation, total/tool timeout, bounded retry, Memory transaction order and
dedupe, ingestion/Evaluation recovery, SSE queue bounds, and startup/shutdown recovery. It retains
the single-API-process assumption. The SSE selection also closes the application stream and proves
its subscriber finalizer runs while the underlying Run remains readable and cancellable.

## 13. Failure injection

`scripts/ci/docker_reliability.py` operates only a validated `agent-studio-task13-*` Compose project.
It stops/restarts only that project's DB/API/Web services. It never uses iptables, daemon kill,
host reboot, global process kill, or a global Docker prune. A `finally` path removes only project
containers, networks, and volumes. A cleanup failure fails the validation and removes any
`DELIVERY READY` artifact instead of being reported as success.

## 14. Worker recovery

Ingestion startup requeues queued/abandoned processing jobs. Evaluation startup marks an interrupted
case ERROR, fails its non-terminal linked Run, and resumes the EvaluationRun. Normal Agent Runs are
not resumable: startup deterministically fails persisted pending/running Runs with the
`process_restart` category so they cannot remain stuck indefinitely. Shutdown first terminates
application-owned Runs and then gives both local workers a bounded drain window before cancellation.

## 15. Database recovery

The container runner proves healthy -> DB down -> safe 503 -> DB up -> healthy. It reloads persisted
Agent, Run, RAG, Memory, and Evaluation evidence. Two hundred database-backed requests must leave
`pg_stat_database.numbackends` inside the generous pool sanity bound. SQLAlchemy `pool_pre_ping` is
exercised after a real DB restart rather than inferred from source. Web restart recovery reloads
the same evidence through the Next.js `/api` proxy, then launches Chromium against the restarted
container and proves the React UI renders the persisted Agent without page or request errors.

## 16. Concurrency

The reliability selection runs 12 concurrent deterministic Calculator Runs and checks unique IDs,
one terminal event, monotonic contiguous event sequences, correct `5192` output, and no escaped task
failure. Existing real PostgreSQL tests retain deterministic barriers for row-lock ordering,
concurrent Memory finalization, duplicate ingestion claims, and a real PostgreSQL barrier that
searches while a replacement generation is processing to prove completed-only visibility.

## 17. Performance philosophy

The performance suite is an engineering regression baseline, not a load test, capacity claim, or
production SLA. It is bounded, synthetic, deterministic, offline from LLM providers, warmed before
measurement, and separated with `pytest.mark.performance`.

## 18. Performance scenarios

The real PostgreSQL/pgvector suite measures API health/list reads, 20 sequential Mock Calculator
Runs, 10 concurrent Runs, synthetic 120-paragraph RAG ingestion, repeated semantic and hybrid
retrieval, ranking across 500 Memory records, repeated trace/metrics reads, and a real 20-case
deterministic Evaluation. Each scenario reports count, duration, throughput, p50, p95, and failure
count where applicable.

## 19. Baseline methodology

`docs/performance-baseline.json` is the reviewed baseline. `PERFORMANCE_OUTPUT` selects the separate
run result, normally `.artifacts/performance-summary.json`. The output records Python, PostgreSQL,
pgvector, platform, git SHA, measurements, and comparison results, but no prompts, document bodies,
Memory contents, secrets, or database URL.

Baseline updates are manual code-review changes. Neither pytest nor a workflow writes the tracked
baseline.

## 20. Threshold methodology

A 1.5x slowdown is report-only. A p95 above 4x baseline or throughput below one quarter baseline is
catastrophic and blocks. Functional failures always block. This deliberately wide band catches
obvious regressions without treating normal GitHub runner noise as a product failure.

## 21. CI artifacts

- Playwright failure trace/report: uploaded only on failure from the two fixed Playwright output
  directories, five days. This directory evidence is not JSON artifact-validator input.
- Reliability metadata: successful safe JSON only, seven days.
- Performance JSON: uploaded for seven days whenever produced, including catastrophic-regression
  failures, after JSON safety validation; missing output is reported explicitly.
- Delivery metadata: successful safe JSON only, seven days.

`validate_repository.py` rejects secret-shaped values/keys, oversized or non-JSON evidence, and
artifact files outside the repository. Database dumps, `.env`, runtime-secret volumes, provider
traces, and caches are never uploaded.

## 22. Timeouts

Every job has `timeout-minutes`. Python wait helpers use explicit timeouts; Docker/HTTP/subprocess
helpers use deadlines; Playwright has 30-second test and 120-second server startup bounds; Compose
waits are at most five minutes. There is no unbounded retry loop.

## 23. Branch protection recommendations

After Task 13 is accepted, configure these exact required checks on main: `Backend`, `PostgreSQL`,
`Frontend`, `Playwright`, `Docker`, `Reliability`, and `Performance`. Repository settings are not
changed by this task. Delivery runs after main and is evidence for delivery readiness, not a PR
approval substitute.

## 24. Security

Workflows are least-privilege and never dump the environment or GitHub token. The repository scan
checks proposed files for private credentials, high-confidence key shapes, conflict markers, unsafe
workflow triggers/permissions, global prune commands, and valid workflow YAML. Dependency audit
output is console-only. The Python audit targets a clean runtime-only dependency installation,
resolves advisory severity through OSV, blocks High/Critical and unclassified findings, and reports
lower severities. A dev/build-only, false-positive, or unreachable exception must be documented in
`dependency-audit-exceptions.json` with a rationale and expiry. The pnpm audit targets production
dependencies and blocks high/critical advisories. Compose gates also assert that DB has no host port and
that no service is privileged or mounts the Docker socket. JSON artifacts are validated before
upload; narrowly scoped Playwright failure directories follow the separate policy above.

## 25. Known limitations

This is not high availability or full chaos engineering. Horizontal/multiprocess API, distributed
workers, managed PostgreSQL, public TLS/ingress, cloud secret management, backup/restore automation,
internet production load, Kubernetes, public deployment, and production SLA remain unimplemented
or untested as documented elsewhere.

## 26. Local reproduction commands

```powershell
# Backend/offline and selected reliability
.\.venv\Scripts\pytest.exe apps/api/tests -m "not postgresql and not real_openai and not real_deepseek and not performance" -q
.\.venv\Scripts\pytest.exe apps/api/tests -m "reliability and not postgresql" -q

# PostgreSQL and performance (set guarded URLs from POSTGRESQL_PGVECTOR.md)
.\.venv\Scripts\pytest.exe apps/api/tests/postgres -m "postgresql and not performance and not real_openai and not real_deepseek" -q
$env:PERFORMANCE_OUTPUT = ".artifacts/performance-summary.json"
.\.venv\Scripts\pytest.exe apps/api/tests/postgres/test_performance_baseline.py -m performance -q -s

# Frontend and browser
pnpm --dir apps/web test:run
pnpm --dir apps/web typecheck
pnpm --dir apps/web lint
pnpm --dir apps/web build --webpack
pnpm --dir apps/web e2e

# Production-like project-scoped reliability/delivery evidence
.\.venv\Scripts\python.exe scripts/ci/docker_reliability.py `
  --project-name agent-studio-task13-local `
  --artifact .artifacts/delivery-metadata.json
```

On Linux use `.venv/bin/...`. The Docker runner performs its own project-scoped cleanup.
