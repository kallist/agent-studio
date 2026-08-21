# Infrastructure

The repository root `compose.yaml` is the minimal local PostgreSQL/pgvector development definition.
`compose.postgres-test.yaml` is a separate loopback-only, tmpfs-backed integration service. Its
initialization SQL adds a restricted database used only to prove that missing pgvector privileges
fail startup clearly.

Status: PostgreSQL 17 container startup, readiness, pgvector, schema initialization, and application
integration are tested. API/web production containers and deployment infrastructure remain out of
scope.
