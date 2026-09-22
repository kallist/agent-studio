# Infrastructure

The repository root `compose.yaml` is the recommended local runtime: PostgreSQL 17 with pgvector, the
production Next.js server, and one Uvicorn API process, with Web and API bound to loopback only and
PostgreSQL kept on an internal network. `compose.deepseek.yaml` and `compose.openai.yaml` add an
opt-in provider secret volume for the API container only.

`compose.postgres-test.yaml` is a separate loopback-only, tmpfs-backed integration service used by the
PostgreSQL and performance CI jobs. Its initialization SQL adds a restricted database used only to
prove that missing pgvector privileges fail startup clearly.

Status: PostgreSQL 17 startup, readiness, pgvector, schema initialization, application integration, and
the production-like API/Web images are tested, including non-root users, cold/warm start, restart
persistence, and container-targeted E2E. Public deployment infrastructure — Kubernetes, managed
PostgreSQL, TLS/ingress, and cloud secret management — is not implemented.
