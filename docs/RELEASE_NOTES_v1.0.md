# Agent Studio v1.0.0 release notes

Agent Studio v1.0.0 is a development and debugging platform for observable, reproducible AI Agent lifecycles. It combines an application-owned runtime with safe tools, RAG, durable Memory, persisted traces, and deterministic Evaluation in one local production-like stack.

## Highlights

- Bounded AgentLoop with explicit steps, retries, timeout, cancellation, terminal state, and ordered events.
- Safe Calculator plus completed-only RAG with asynchronous ingestion, citations, PostgreSQL 17, and pgvector HNSW retrieval.
- Agent-scoped durable Memory with policy, ranking, dedupe, expiration, deletion, and row-lock concurrency semantics.
- Run/RunEvent observability and isolated PASS/FAIL/ERROR Evaluation linked to real persisted Runs.
- Deterministic Mock default, real-tested DeepSeek provider, and an implemented OpenAI boundary whose live path remains NOT TESTED.
- Non-root production images, loopback-only services, runtime secrets, Docker persistence/recovery, and automated CI/Delivery gates.

## Start

From the repository root:

```powershell
docker compose up --build -d
```

Open `http://127.0.0.1:3000` and follow [the demo](DEMO.md). No LLM key is required.

## Validation boundary

The v1 candidate is validated by offline backend tests, real PostgreSQL/pgvector tests, Ruff, strict mypy, Vitest, TypeScript, ESLint, a webpack production build, deterministic Playwright, Docker startup and container E2E, bounded reliability scenarios, a synthetic performance baseline, and GitHub CI/Delivery Validation. Exact release-candidate results belong in the PR and GitHub Release, not as permanent counts in this file.

## Known limitations

This is a single-user local workbench, not an internet-ready SaaS. Authentication, RBAC, multi-tenancy, distributed workers, Kubernetes, public TLS/ingress, managed infrastructure, backup automation, cloud secret management, automatic public deployment, high availability, and production SLA are not implemented. Real OpenAI Responses/embeddings/OpenAI-plus-pgvector and internet production load are not tested.

See [the claim matrix](V1_STATUS.md) for the complete status boundary.
