# Cross-application fixtures

Application tests live with their application: `apps/api/tests` for pytest and `apps/web/e2e` for
Playwright. This directory holds only fixtures shared across that boundary.

`tests/fixtures/rag/` contains small original documents used by retrieval tests, including
`benchmark.json`, which records deterministic recall expectations for those fixtures. It is a
regression fixture, not a published retrieval benchmark.

See the repository [README](../../README.md) for the full quality and validation commands.
