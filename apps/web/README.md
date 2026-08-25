# Agent Studio web

This directory owns the Next.js frontend described in `docs/ARCHITECTURE.md`. It includes Studio,
Playground, Knowledge, Runs, Evaluation, and Dashboard product paths with Vitest and Playwright
coverage.

For the recommended production-like local runtime, start the repository-level Docker Compose stack;
the browser uses same-origin `/api` requests proxied by the standalone Next.js server. Host-native
development remains available through the commands in `docs/DEVELOPMENT.md`.
